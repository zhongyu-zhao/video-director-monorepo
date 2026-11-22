# screenplay-adapter 架构与路线图

本文写当前实现和计划中的结构。为什么先做确定性改编计划、为什么计划是事实源，见 [`docs/decisions/proposed/architecture/2026-11-22-adaptation-kernel.md`](decisions/proposed/architecture/2026-11-22-adaptation-kernel.md)；字段契约见 [`2026-11-22-adaptation-plan-contract.md`](decisions/proposed/architecture/2026-11-22-adaptation-plan-contract.md)。本文不重复论证。

## 目标

把小说或故事大纲变成可核对、可编辑、可继续拍摄的视频剧本：每一场能回到原文的连续句子区间，每一个结构位置有依据，人物不越权，时长和格式可检查；正文由模型或人写，但不能绕过计划。

## 当前的 M0 内核

```text
source.md
  → 章节/段落/句子（字符偏移）
  → 人物表（对白归属 + 显式覆盖）
  → adaptation.json（场次/集/节拍/时长/来源锚点/覆盖）
  → briefs.md（逐场写作 brief）
  → draft（LLM 或人）→ drafts/S*.json
  → assemble → screenplay.json
  → screenplay.fountain / screenplay.md
  → validate → report.json
```

实现位于 `screenplay_adapter/`：

| 模块 | 职责 | 状态 |
|---|---|---|
| `source.py` | 章节/段落/句子、偏移、引号感知切句 | M0 |
| `cast.py` | 对白归属、别名、显式人物表 | M0 |
| `beats.py` | 15 拍/剧集/短剧模板、节拍归属 | M0 |
| `plan.py` | 场次分配、章节优先切分、时长、覆盖、brief | M0 |
| `writer.py` | prompt、OpenAI 兼容 HTTP、响应校验 | M0 |
| `draft.py` | 草稿合并、统计 | M0 |
| `validate.py` | 计划/剧本确定性门 | M0 |
| `fountain.py` | Fountain/Markdown 视图 | M0 |
| `project.py` | 项目目录、原子写、哈希、env | M0 |
| `cli.py` | `adapt` / `draft` / `assemble` / `validate` | M0 |
| 人物状态机 / 因果情节图 / 自动改写 / 评分 | 长程一致性与质量 | M1 |
| 分镜/机位/双人对白交接 | 下游 | M2 |

## 项目目录

```text
project/
  source/source.md      # 规范化输入副本，本地使用
  adaptation.json       # 计划，事实源
  briefs.md             # 阅读/写作 brief
  drafts/S001.json      # 逐场草稿
  screenplay.json       # 剧本，事实源
  screenplay.fountain   # 导出视图
  screenplay.md         # 评审视图
  report.json           # 最近一次门结果
```

所有生成物都由 `adaptation.json` + `screenplay.json` 重建；Fountain/Markdown 不是第二份事实。

## 核心不变量

1. **覆盖**：每场引用连续句子区间；从第 0 句到第 N-1 句恰好覆盖一次，除非计划因源太稀疏降级并有 warning。
2. **顺序**：场景 id `S001...`、集号单调、集内场号从 1 连续。
3. **时长**：每场 > 0，总和等于目标总时长（±0.5s）；单场目标由总时长/场数均分。
4. **人物**：计划里的在场人物必须来自人物表；剧本对白说话人必须来自人物表（含别名）。
5. **指纹**：计划哈希由 `source_sha256 + brief + cast + scenes` 计算；草稿带计划/原文/prompt 指纹；不匹配拒绝合并。
6. **来源**：`source.sentence_start/end` 和 `char_start/end` 指向规范化副本；导出时从句子重建文本，不把章节标题带进正文。

## 场次规划

1. 目标总秒数 = 集数 × 单集分钟 × 60。
2. 期望场数 = `round(总秒数 / 目标单场秒)`。
3. 章节优先：
   - 场数 ≥ 有句子的章节数：每章至少一场，按字符量分配剩余场次；章内再按句子切。
   - 场数 < 章节数：把相邻章节按字符量分组，每组一场，避免从章节标题中间开场。
4. 场数上限是源句子数；源太稀疏时降级并 warning，不伪造空场。
5. 场时长均分；集号按场序均分，保证每个请求的集至少一场（场数不足时 fail）。
6. 节拍：长片用全片进度；短剧/剧集用集内场位置。场数足够时首场对齐第一个节拍、末场对齐最后一个节拍；单场集只能取一个节拍，计划会给 warning，写作者要自己兼顾开场和卡点。

## 写作

- `draft` 一次只写一场。prompt 只带：项目 brief、人物表、本场原文、前后场一句摘要、本场节拍/时长/在场人物/扩写提示、输出 JSON schema。
- `mode=expand` 时，除原文密度明显偏高的场外，每场都会得到 `expand` 提示：源文本只是骨架，写作者要补动作、反应和对白；内核仍不替模型发明情节。
- 模型返回 JSON，解析后校验场景头/动作/对白/来源标记，再写 `drafts/S*.json`。
- 失败按场隔离：继续写其他场，最后报告缺失场；认证/端点错误立即停止。
- 没有自动重试改写；重写是显式 `--force` 重跑某几场。

## 验收

| 类别 | 门 | fail/warn |
|---|---|---|
| 计划结构/覆盖/哈希 | P001–P006, P011–P012 | fail |
| 人物引用 | P007 | fail |
| 节拍/章节 | P008–P009 | fail / warn |
| 计划 warning | P010 | warn |
| 剧本结构/链接 | S000–S005 | fail |
| 人物/来源标记 | S006–S007 | fail |
| 时长估算/无对白/新增比例 | S008–S010 | warn |
| 草稿人物 vs 计划检测 | S011 | warn |

`fail` 阻止交付；`warn` 进人工复核；没有 `skip` 伪装成通过。`assemble` 先在内存里验证合并后的剧本：`fail` 时只写 `report.json`，不写 `screenplay.json`/Fountain/Markdown，并清掉上一次的同名产物；`pass`/`warn` 才落盘。语义质量（角色声音、主题、表演）不在门里，必须人读。

## 格式与导出

- **Fountain**：title page、`# 第 N 集` section、`INT./EXT. 地点 - 时间`、动作、角色、括号提示、对白、转场；`[[source: S001 | CH001 | 45s]]` 保留锚点。动作行若以 `INT.` 等开头会加 `!` 强制当动作。
- **Markdown**：按集/场展开，带来源句区间、目标/估算时长、对白来源比例和原文摘录，供人评审。
- 输出只依赖 `screenplay.json`，不重新解释模型响应。

## 路线图

- **M0 确定性内核（当前）**：解析、人物、计划、逐场写作、合并、Fountain/Markdown、门。
- **M1 长程一致性**：人物状态/已知信息/关系变化落盘；场间因果边；跨场连续性检查；部分重写与版本快照；语义评审（对白连贯/人物一致/情节合理）作为 warning。
- **M2 生产交接**：分镜/镜头表、场景/地点/道具/服装清单、集数/时长预算、与 video-director 的版本化契约；多候选与人工选择。
- **M3 规模化**：长篇小说滑窗摘要、章节级 map-reduce、缓存与成本账本、批量项目、Web/审阅 UI。

每个阶段都保持“计划可核对、草稿可重跑、导出可重建”，不在中间态失联。

## 与其他子 repo 的边界

- 不 import `auto-shot` 或 `video-director` 的代码。
- 可选的交换格式是版本化 JSON：本项目输出 `screenplay.json`，video-director 按自己的契约消费；auto-shot 的 `screenplay.json` 是反向分析产物，schema 不同，不共享类型。
- 没有另外两个子 repo 也能独立运行。

## 非目标

- M0 不做“一键生成可拍成片”的承诺；不评估表演、镜头调度和最终质量。
- 不把模型输出直接当 `adaptation.json`；不让 LLM 改场次边界。
- 不为单一 provider 写死；当前只实现 OpenAI 兼容协议，其他协议按需加 adapter。
- 不提交受版权保护的小说原文或生成剧本。
