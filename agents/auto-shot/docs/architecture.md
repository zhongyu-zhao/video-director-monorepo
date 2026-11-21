# auto-shot 架构与路线图

本文写当前实现和计划中的结构。为什么这样分层见 [`docs/decisions/proposed/architecture/2026-11-21-auto-shot-pipeline.md`](decisions/proposed/architecture/2026-11-21-auto-shot-pipeline.md)；本文不重复论证。

## 目标

输入一部电影/剧集/短片，输出“可核对、可编辑、可导出”的镜头表和逐镜视听语言分析。镜头表是唯一事实源，报告只是它的一个视图。

## 当前流水线

```text
input.mp4
   │
   ├─ probe      ffprobe：时长/帧率/画幅/音轨          ──► media facts
   ├─ detect     ffmpeg scene score：候选切点            ──► cuts
   ├─ table      cuts + duration → shots.json            ──► 镜头表
   ├─ validate   时间轴/镜号/时长/词表质量门              ──► quality.json
   ├─ report     shots.json → report.md                  ──► 镜头表视图
   ├─ review     shots.json + video → review.html        ──► 人工核对
   ├─ apply      review-flags.json → shots-reviewed.json ──► 修正镜头表
   └─ label      shots.json + video + VLM → labels.json  ──► 逐镜标签
```

实现位于 `auto_shot/`：

| 模块 | 职责 | 状态 |
|---|---|---|
| `probe.py` | ffprobe 边界，只产出媒体事实 | 已有 |
| `detect.py` | ffmpeg 场景检测，产出候选切点 | 基线 |
| `models.py` | 镜头表数据结构与 JSON 读写 | 已有 |
| `quality.py` | 确定性质量门 | 已有 |
| `report.py` | Markdown 镜头表 | 已有 |
| `pipeline.py` | 串起分析阶段 | 已有 |
| `review.py` | 复核 HTML 生成 + 应用人工修正 | 已有 |
| `taxonomy.py` | 标签枚举校验 | 已有 |
| `vlm.py` / `label.py` | VLM 客户端、逐镜标注、缓存 | 单帧起步 |
| measure / scenes | 测量、场景聚合 | 计划中 |

## 产物

```text
out/
  shots.json              # schema_version, video, detector, shots, manual_cuts
  quality.json            # ok, checks[]
  report.md               # 人读的镜头表视图
  review.html             # 单文件复核页
  review-flags.json       # 页面导出：falseCuts / missedCuts
  shots-reviewed.json     # 应用复核后的镜头表
  shots-reviewed-report.md
  labels.json             # VLM 标签：labels/content/evidence/confidence/provenance
  labels.md               # 标签的人读视图
  frames/                 # 标注用关键帧
```

字段契约见 [`2026-11-21-shot-table-contract.md`](decisions/proposed/architecture/2026-11-21-shot-table-contract.md)。镜头表保持事实层；VLM 标签先放 `labels.json`，等字段稳定后再合并进镜头表。

## 切点复核闭环

默认阈值是 0.25，比最初的 0.3 召回更高；代价是闪光、黑场和快速运动会带来伪切点，而低对比度的特写→宽景切点仍可能漏掉。复核页用于处理这两类错误：

- `review` 生成单文件 HTML，播放器 + 镜头列表；点击/←→跳到切点前 0.6s。
- 页面可勾选误切、按 `m` 记录漏切；标记在 `localStorage`，导出 `review-flags.json`。
- `apply-review` 将误切并入前一镜、漏切拆开，重编号，写入 `manual_cuts`，再跑质量门。
- 原 `shots.json` 不被覆盖；修正结果另存，随时可对比/回退。

为什么不是纯调阈值：同一集从 0.3 的 508 镜降到 0.25 的 624 镜，降低阈值会增加召回也会引入伪切点，单靠阈值无法兼顾。详见 [`2026-11-21-human-review-loop.md`](decisions/proposed/feature/2026-11-21-human-review-loop.md)。

## VLM 标签

第一版只给模型一帧（镜头中点，480 宽），要求输出：

- `labels`：景别/角度/构图/光线/色彩/景深，只能取词表枚举值；单帧的 `camera` 固定 `unknown`。
- `content`：主体 + 一句可核对的动作描述。
- `evidence`：至少一条观察依据。
- `confidence`：每个维度 0–1。

标签写入独立 `labels.json`，带 `shot_hash`、`prompt_version`、模型名和 `provenance`；缓存 key 是 `video identity + shot_hash + prompt_version + model`。模型返回非法枚举、缺字段或伪造运镜时，该镜记为错误，不写入标签。详见 [`2026-11-21-vlm-shot-labeling.md`](decisions/proposed/feature/2026-11-21-vlm-shot-labeling.md)。

## 质量门

已实现：

- `schema_version`：版本一致。
- `shots_present`：镜头表不能为空。
- `timeline_starts_at_zero`：从 0 开始。
- `timeline_contiguous`：下一镜入点等于上一镜出点（1ms 容差）。
- `timeline_covers_media`：最后一镜覆盖到片尾（帧容差）。
- `positive_durations`：每镜时长大于 0。
- `sequential_ids`：`S001..Snnn` 连续。
- `transition_vocabulary`：转场只能取词表值，首镜为 `start`。
- `manual_cuts_valid`：人工切点在范围内且递增；检测结果没有人工切点，记为 `skip`；`apply-review` 会写入。

M1/M2 再加入：标签枚举/证据质量门、运动与实测一致、描述可核对、主体对账。`skip` 表示“没有证据/尚不适用”，永远不算通过。

## 路线图

- **M0 镜头表内核（已完成）**：probe、基线切分、镜头表、质量门、Markdown 报告。
- **人工复核闭环（已完成）**：review HTML、误切/漏切标记、apply-review、manual_cuts。
- **VLM 逐镜标注（单帧起步）**：单帧静态标签 + 证据 + 置信度；多帧/联系表、上下文和叙事功能仍待补。
- **M1 证据层**：代理转码、黑边检测、关键帧/联系表、运动/亮度/色彩/人脸测量、ASR/音频事件、可替换 SBD（PySceneDetect / TransNetV2 / OmniShotCut）。
- **M2 标注质量**：多帧输入、批量 reduce、质量门 v2、低置信度重跑、人工确认。
- **M3 场景与报告**：镜头聚合、场景卡、全片统计、证据回链、HTML/CSV 导出。
- **M4 交互与问答**：`search_shots`、`compare_shots`、`render_clip`、播放器联动、增量重跑。

单帧 VLM 是刻意提前的窄切片：先验证“标签/证据/缓存/密钥边界”能跑通，不宣称已经解决视听语言理解。

## 与其他子 repo 的边界

- 不 import `video-director` 的代码。
- 需要把镜头表交给 video-director 时，导出 `shots.json`（或 `shots-reviewed.json`），由下游按自己的契约校验。
- 共享的是版本化 JSON，不是 Python 类型或内部模块。

## 非目标

- 不生成或剪辑视频。
- 不写影评、不做“一键拉片”的叙事结论。
- 检测/测量不依赖商业 API；VLM provider 可替换，不写入事实层。
- 不把整片塞进单次模型调用。
