# video-director

视频制作 agent 子 repo：把创作意图变成可核对、可编辑、可导出的视频产物。

当前处于 **M0（确定性内核）**：项目模型、单轨时间线、项目校验、本地素材的 FFmpeg 拼接渲染和 ffprobe 验收。规划、生成、质检、多轨、转场和交互 UI 还没有实现，路线图见 [`docs/architecture.md`](docs/architecture.md)。

## 要求

- Python 3.12+
- `ffmpeg` / `ffprobe` 6.x（需要 libx264）

## 快速开始

```bash
cd agents/video-director

python3 -m video_director init --root /tmp/demo --title demo --fps 25 --size 320x180
python3 -m video_director asset add /path/to/clip-a.mp4 --root /tmp/demo
python3 -m video_director asset add /path/to/clip-b.mp4 --root /tmp/demo
python3 -m video_director clip add --root /tmp/demo --asset A001 --in 0 --out 2
python3 -m video_director clip add --root /tmp/demo --asset A002 --in 0 --out 2
python3 -m video_director validate --root /tmp/demo
python3 -m video_director render --root /tmp/demo
```

渲染默认输出 `renders/render-r<revision>.mp4`，验收结果写 `renders/render_report.json`。

退出码：`0` 成功且检查通过；`1` 校验/渲染检查失败；`2` 输入、项目文件或 ffmpeg 错误。

## 项目目录

```text
project/
  project.json     # 当前事实源
  artifacts/       # 后续阶段工件
  assets/          # 本地素材，不入 git
  renders/         # 渲染产物 + render_report.json
  history/         # 每个 revision 的项目快照
```

`project.json` 的字段和约束见 [`docs/decisions/proposed/architecture/2026-11-21-project-timeline-contract.md`](docs/decisions/proposed/architecture/2026-11-21-project-timeline-contract.md)。

## 测试

```bash
cd agents/video-director
python3 -m unittest discover -v
```

渲染集成测试会用 ffmpeg 生成两段 2 秒的纯色素材，拼接后验证时长、分辨率、fps；缺少 ffmpeg 时自动跳过。

## M0 的边界

- 只有一条视频轨；没有转场、叠加、字幕、音频。
- 只渲染本地视频素材；图片/音频资产可以登记，但不参与渲染。
- 没有生成、规划、剧本/分镜阶段；这些是 M1/M2。
- 没有 UI；编辑通过 CLI 和 `project.json` 进行，所有修改走 revision 快照。
- 没有外部素材引用；素材必须复制进 `assets/`，项目才能整体搬移。

## 目录

```text
video_director/
  cli.py       # init / asset add / clip add / validate / render
  models.py    # Project / Asset / TimelineClip
  project.py   # 项目读写、revision 快照、素材与片段操作
  validate.py  # 项目校验门
  render.py    # 单轨确定性渲染 + ffprobe 验收
  media.py     # ffmpeg/ffprobe 边界
tests/         # 单元测试 + 合成素材渲染集成测试
docs/          # 架构与决策记录
```

## 文档

- 架构与路线图：[`docs/architecture.md`](docs/architecture.md)
- 内核决策：[`docs/decisions/proposed/architecture/2026-11-21-video-director-kernel.md`](docs/decisions/proposed/architecture/2026-11-21-video-director-kernel.md)
- 项目/时间线契约：[`docs/decisions/proposed/architecture/2026-11-21-project-timeline-contract.md`](docs/decisions/proposed/architecture/2026-11-21-project-timeline-contract.md)

## 与其他子 repo 的边界

video-director 不 import `auto-shot` 的代码。可以消费 auto-shot 导出的 `shots.json` 作为镜头表输入，但必须按本项目自己的契约校验；没有 auto-shot 也能独立运行。仓库级约定见 [`../../AGENTS.md`](../../AGENTS.md)。
