# video-director 架构与路线图

本文写当前实现和计划中的结构。为什么先做确定性内核、为什么时间线是事实源，见 [`docs/decisions/proposed/architecture/2026-11-21-video-director-kernel.md`](decisions/proposed/architecture/2026-11-21-video-director-kernel.md)；本文不重复论证。

## 目标

把创作意图变成可核对、可编辑、可导出的视频产物。分镜/镜头表是编辑层，时间线是唯一事实源；预览和成片都从时间线渲染，而不是一次性生成一个不可修改的 MP4。

## 当前的 M0 内核

```text
init ──► project.json + history/project-r001.json
asset add ──► assets/A001.mp4 + revision + snapshot
clip add  ──► timeline clips + revision + snapshot
validate  ──► 路径/引用/时间线/范围检查
render    ──► 逐段 trim+scale+fps ──► concat ──► ffprobe 验收 ──► render_report.json
```

实现位于 `video_director/`：

| 模块 | 职责 | 状态 |
|---|---|---|
| `models.py` | Project / Asset / TimelineClip / Timeline | M0 |
| `project.py` | 项目读写、revision 快照、素材复制、片段追加、路径安全 | M0 |
| `validate.py` | 渲染前确定性检查 | M0 |
| `render.py` | 单轨 FFmpeg 渲染与验收 | M0 |
| `media.py` | ffmpeg/ffprobe 边界 | M0 |
| `cli.py` | `init` / `asset add` / `clip add` / `validate` / `render` | M0 |
| tools / planning / generation / qc | 工具层、规划 DAG、生成、质检 | 计划中 |

## 项目结构

```text
project/
  project.json     # schema_version, project_id, title, status, revision,
                   # fps, width, height, assets[], timeline{clips[]}
  artifacts/       # 提案/剧本/分镜/资产清单/剪辑决策（后续阶段）
  assets/          # 本地素材，相对路径引用，不入 git
  renders/         # render-r<NNN>.mp4 + render_report.json
  history/         # project-r<NNN>.json，每个 revision 的完整快照
```

字段契约见 [`2026-11-21-project-timeline-contract.md`](decisions/proposed/architecture/2026-11-21-project-timeline-contract.md)。

## 时间线约束

M0 只有一条连续视频轨：

- 第一个片段从 0 开始。
- 下一片段 `start` 等于上一片段 `start + duration`；不留空隙、不重叠。
- `duration = source_out - source_in`；时间用秒，保留 3 位。
- 素材必须存在且位于项目目录内；`source_out` 不能超出素材时长。
- 空时间线是合法的草稿，但不可渲染。

## 渲染与验收

- 每段先用 FFmpeg 裁剪到 `source_in..source_out`，统一缩放到项目分辨率（保持比例并补边）、项目 fps、`yuv420p`、libx264。
- 所有片段编码参数一致，再用 concat demuxer 无损拼接。
- 渲染后用 ffprobe 验证：输出存在、片段数、总时长、分辨率、fps。
- 验收结果写到 `renders/render_report.json`，记录 `project_revision` 和每项检查；任何 `fail` 使渲染视为失败。
- 音频在 M0 明确忽略，报告里记为 `skip`，不假装通过。

## 路线图

- **M0 确定性内核（当前）**：项目模型、版本快照、单轨时间线、校验、FFmpeg 渲染、ffprobe 验收。
- **M1 工具层**：统一 `ToolSpec`（name / JSON Schema / permission / concurrency / cost）、provider adapter、成本账本（estimate / reserve / reconcile，cap）、项目编辑工具（append / trim / move / split）。
- **M2 规划层**：代码 DAG 管阶段（提案 → 剧本 → 分镜/镜头表 → 资产 → 剪辑），每阶段工件 schema + checkpoint；LLM 只做阶段内决策和失败重规划。
- **M3 生成与质检**：图像/视频/TTS provider、资产注册表、参考图/首尾帧、best-of-N + VLM 评审、确定性 QC（ffprobe/抽帧/音频/字幕）、人审 gate。
- **M4 skill 化与交互**：把每类视频的 know-how 写成 manifest + skill；Web UI/播放器联动；多轨、转场、字幕。

每个阶段都要保持“时间线可渲染、工程可恢复”，不在中间态失联。

## 与其他子 repo 的边界

- 不 import `auto-shot` 的代码。
- 可选消费 auto-shot 导出的 `shots.json`，但由 video-director 自己的契约校验；没有 auto-shot 也能独立运行。
- 共享的是版本化 JSON 文件，不是 Python 类型或内部模块。

## 非目标

- M0 不做生成、规划、剧本/分镜创作。
- M0 不支持多轨、转场、音频、字幕、图片序列。
- 不把最终 MP4 当项目状态；MP4 只是某个 revision 的渲染产物。
- 不绑定单一生成 provider 或渲染器；FFmpeg 只是第一个渲染后端。
