# screenplay-adapter

小说扩写 / 改编子 repo：把小说或故事大纲变成可核对、可编辑、可继续拍摄的视频剧本。

当前处于 **M0（确定性改编内核）**：解析章节和句子、抽人物、生成带来源锚点的场次计划、按 brief 逐场写作、合并导出 Fountain/Markdown，并跑覆盖/人物/格式/时长门。改计划后旧草稿会被指纹拒绝，`draft` 需要 `--force` 才覆盖。人物状态机、因果情节图、自动改写循环和 UI 还没有实现。

## 要求

- Python 3.12+
- 无第三方运行时依赖
- 可选：任意 OpenAI 兼容的 chat-completions 端点（只有 `draft` 需要）

## 快速开始

```bash
cd agents/screenplay-adapter

# 1) 解析小说并生成改编计划（不调用模型）
python3 -m screenplay_adapter adapt /path/to/novel.md \
  --root /tmp/adapt \
  --title 雨夜 \
  --format short-drama \
  --episodes 30 \
  --episode-minutes 2 \
  --scene-seconds 45

# 源文本是大纲/短篇时，用扩写模式让每场 brief 明确要求补动作/对白
python3 -m screenplay_adapter adapt outline.md --root /tmp/expand --title 无题 \
  --format feature --mode expand

# 2) 逐场写作（OpenAI 兼容端点）
python3 -m screenplay_adapter draft \
  --root /tmp/adapt \
  --env-file /path/to/.env \
  --model gpt-4o-mini

# 3) 合并草稿、导出 Fountain/Markdown、跑验收
python3 -m screenplay_adapter assemble --root /tmp/adapt

# 4) 只重跑确定性门
python3 -m screenplay_adapter validate --root /tmp/adapt
```

`--env-file` 读取 `KEY=VALUE`。支持：

```dotenv
SCREENPLAY_ADAPTER_BASE_URL=https://api.openai.com/v1
SCREENPLAY_ADAPTER_API_KEY=...
SCREENPLAY_ADAPTER_MODEL=gpt-4o-mini
```

也接受 `OPENAI_BASE_URL` / `OPENAI_API_KEY` / `OPENAI_MODEL`。key 只从 env 文件或进程环境读取，不写进项目产物。`draft` 会把本场原文和人物表发给配置的 provider；非 loopback 地址必须用 HTTPS（本机 HTTP 端点仅允许 loopback）。

格式预设（可用 `--episodes` / `--episode-minutes` / `--scene-seconds` 覆盖）：

| format | 集数 | 单集分钟 | 目标场秒 | 适用 |
|---|---|---|---|---|
| `short-drama` | 30 | 2 | 45 | 竖屏微短剧 |
| `series` | 6 | 45 | 180 | 剧集 |
| `feature` | 1 | 100 | 150 | 电影长片 |

退出码：`0` 通过（允许 warn）；`1` 有 fail 门或部分场景写作失败；`2` 输入、项目或 provider 配置错误。

## 人物表

默认从对白归属自动抽人物（`“你迟到了。”顾远说。`），抽不到重要角色时用显式人物表：

```bash
python3 -m screenplay_adapter adapt novel.md --root /tmp/adapt --title 雨夜 --cast cast.json
```

```json
{
  "characters": [
    {"name": "林昭", "aliases": ["阿昭"], "role": "主角", "note": "记者"},
    {"name": "顾远", "aliases": []}
  ]
}
```

显式人物表是权威：不在表里的名字不能出现在对白中。新增角色要改人物表，不能让模型在剧本里临时造人。

## 项目目录

```text
project/
  source/source.md      # 输入文本的规范化副本（本地使用，不提交）
  adaptation.json       # 改编计划，事实源
  briefs.md             # 逐场写作 brief
  drafts/S001.json      # 逐场草稿，独立落盘
  screenplay.json       # 合并后的剧本，事实源
  screenplay.fountain   # Fountain 导出视图
  screenplay.md         # 人读/评审视图
  report.json           # 最近一次确定性验收
```

`adaptation.json` 和 `screenplay.json` 的字段契约见 [`docs/decisions/proposed/architecture/2026-11-22-adaptation-plan-contract.md`](docs/decisions/proposed/architecture/2026-11-22-adaptation-plan-contract.md)。

## 当前能力

- **章节/句子解析**：Markdown 标题、`第 N 章`、`Chapter N`、至少两个数字标题（如 `1. 起点`）；保留字符偏移，按引号深度切句。
- **人物抽取**：对白归属 + 引号上下文 + 停用词；支持显式人物表和别名。
- **场次计划**：按目标总时长/单场时长算场数；优先按章节分配，章节太多时合并相邻章节；每场有连续源句子区间、目标时长、结构节拍、在场人物和扩写/压缩提示。
- **结构模板**：长片用 15 拍，短剧/剧集用每集“钩子—升级—反转/复杂化—卡点”；模板是数据，不是创作判断。
- **逐场写作**：OpenAI 兼容端点；每场只给本场原文、人物表、节拍、时长和硬约束；草稿独立落盘，带 plan/source/prompt 指纹（计划哈希覆盖源、brief、人物表、场次）。
- **验收门**：源句子覆盖、场次/集顺序、时长总和、人物引用、节拍单调、场景头、动作/对白、说话人、对白来源标记、估算时长偏差、新增比例。`assemble` 只在 `pass`/`warn` 时写 `screenplay.*`；`fail` 时只写 `report.json`，并清掉旧的同名产物。
- **导出**：Fountain（可导入剧本软件）和 Markdown（评审用）；JSON 始终是事实源。

## 测试

```bash
cd agents/screenplay-adapter
python3 -m unittest discover -v
```

测试不访问外部网络：writer 测试用本地假 HTTP server，其余用固定合成文本。不需要安装包。

## M0 的边界

- 不一次调用生成整本剧本；没有自动改写循环、没有多候选/best-of-N。
- 没有人物状态机、因果关系图、场次评分或语义质量模型；这些是 M1。
- 不做分镜、机位、双人对白、字幕、TTS 或渲染；这些交给下游子 repo。
- 只有 OpenAI 兼容的 chat-completions 适配器；没有绑定特定供应商。
- 时长是启发式估算（中文约 4 字/秒），只做量级检查，不是精确片长。
- 不提交小说原文、草稿或生成剧本；项目目录默认放仓库外或 `adaptations/`。

## 目录

```text
screenplay_adapter/
  source.py     # 章节/段落/句子解析，字符偏移
  cast.py       # 人物抽取、别名、显式人物表
  beats.py      # 结构模板与节拍归属
  plan.py       # 场次分配、时长、来源锚点、brief
  writer.py     # prompt + OpenAI 兼容 HTTP 适配器
  draft.py      # 草稿合并、统计
  validate.py   # 计划/剧本确定性门
  fountain.py   # Fountain / Markdown 导出
  project.py    # 项目目录 IO、哈希、env
  cli.py        # adapt / draft / assemble / validate
tests/          # 单元 + CLI + 假 provider 集成测试
docs/           # 架构与决策记录
```

## 文档

- 架构与路线图：[`docs/architecture.md`](docs/architecture.md)
- 内核决策：[`docs/decisions/proposed/architecture/2026-11-22-adaptation-kernel.md`](docs/decisions/proposed/architecture/2026-11-22-adaptation-kernel.md)
- 工件契约：[`docs/decisions/proposed/architecture/2026-11-22-adaptation-plan-contract.md`](docs/decisions/proposed/architecture/2026-11-22-adaptation-plan-contract.md)
- 调研快照：[`../../docs/research/2026-11-novel-to-screenplay-survey.md`](../../docs/research/2026-11-novel-to-screenplay-survey.md)

## 与其他子 repo 的边界

- 不 import `auto-shot` 或 `video-director` 的代码。
- 产出的 `screenplay.json` 是版本化 JSON，可以交给 video-director 作为剧本/场次输入，但由消费方按自己的契约校验；没有另外两个子 repo 也能独立运行。
- `auto-shot` 的“剧本还原”是从成片反推的分析产物，和本项目的“改编计划”不是同一个 schema，不共享类型。
- 仓库级约定见 [`../../AGENTS.md`](../../AGENTS.md)。
