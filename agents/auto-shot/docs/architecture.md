# auto-shot 架构与路线图

本文写当前实现和计划中的结构。为什么这样分层见 [`docs/decisions/proposed/architecture/2026-11-21-auto-shot-pipeline.md`](decisions/proposed/architecture/2026-11-21-auto-shot-pipeline.md)；本文不重复论证。

## 目标

输入一部电影/剧集/短片，输出“可核对、可编辑、可导出”的镜头表和逐镜视听语言分析。镜头表是唯一事实源，报告只是它的一个视图。

## 当前的 M0 流水线

```text
input.mp4
   │
   ├─ probe      ffprobe：时长/帧率/画幅/音轨          ──► media facts
   ├─ detect     ffmpeg scene score：候选切点            ──► cuts
   ├─ table      cuts + duration → shots.json            ──► 镜头表
   ├─ validate   时间轴/镜号/时长/词表质量门              ──► quality.json
   └─ report     shots.json → report.md                  ──► 镜头表视图
```

实现位于 `auto_shot/`：

| 模块 | 职责 | 状态 |
|---|---|---|
| `probe.py` | ffprobe 边界，只产出媒体事实 | M0 |
| `detect.py` | ffmpeg 场景检测，产出候选切点 | M0 基线 |
| `models.py` | 镜头表数据结构与 JSON 读写 | M0 子集 |
| `quality.py` | 确定性质量门 | M0 子集 |
| `report.py` | Markdown 镜头表 | M0 |
| `pipeline.py` | 串起 M0 阶段 | M0 |
| `cli.py` | `auto-shot analyze` | M0 |
| measure / label / scenes | 测量、VLM 标注、场景聚合 | 计划中 |

## 产物

```text
out/
  shots.json     # schema_version, video, detector, shots, manual_cuts
  quality.json   # ok, checks[]
  report.md      # 人读的镜头表视图
```

字段契约见 [`2026-11-21-shot-table-contract.md`](decisions/proposed/architecture/2026-11-21-shot-table-contract.md)。M0 只写其中的事实子集；`labels`、`content`、`function`、`evidence`、`confidence` 在 M2 加入，按 additive 方式扩展。

## 质量门

M0 已经实现：

- `schema_version`：版本一致。
- `shots_present`：镜头表不能为空。
- `timeline_starts_at_zero`：从 0 开始。
- `timeline_contiguous`：下一镜入点等于上一镜出点（1ms 容差）。
- `timeline_covers_media`：最后一镜覆盖到片尾（帧容差）。
- `positive_durations`：每镜时长大于 0。
- `sequential_ids`：`S001..Snnn` 连续。
- `transition_vocabulary`：转场只能取词表值，首镜为 `start`。
- `manual_cuts_valid`：人工切点在范围内且递增；M0 无人工切点，记为 `skip`。

M1/M2 再加入：枚举合法、证据存在、运动与实测一致、描述可核对、主体对账。`skip` 表示“没有证据/尚不适用”，永远不算通过。

## 路线图

- **M0 镜头表内核（当前）**：probe、基线切分、镜头表、质量门、Markdown 报告。
- **M1 证据层**：代理转码、黑边检测、关键帧/联系表、运动/亮度/色彩/人脸测量、ASR/音频事件、可替换 SBD（PySceneDetect / TransNetV2 / OmniShotCut）。
- **M2 逐镜标注**：VLM 批次标注、枚举 + 证据 + 置信度、质量门 v2、低置信度重跑、人工确认。
- **M3 场景与报告**：镜头聚合、场景卡、全片统计、证据回链、HTML/CSV 导出。
- **M4 交互与问答**：`search_shots`、`compare_shots`、`render_clip`、播放器联动、增量重跑。

每个里程碑独立可交付；没有完成 M1 之前不做 M2 的“洞察”。

## 与其他子 repo 的边界

- 不 import `video-director` 的代码。
- 需要把镜头表交给 video-director 时，导出 `shots.json`，由下游按自己的契约校验。
- 共享的是版本化 JSON，不是 Python 类型或内部模块。

## 非目标

- M0 不生成或剪辑视频。
- M0 不写影评、不做“一键拉片”的叙事结论。
- M0 不接商业视频 API；后续作为可插拔 provider，不作为内核。
- 不把整片塞进单次模型调用。
