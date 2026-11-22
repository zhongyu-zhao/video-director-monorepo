# video-director-monorepo

视频导演 Agent 的 monorepo：把创作意图变成可核对、可编辑、可导出的视频产物。

当前包含三个独立子 repo：

- [auto-shot](agents/auto-shot/README.md)：自动拉片——切分镜头，并逐镜分析视听语言。
- [video-director](agents/video-director/README.md)：视频制作——从创作意图到可编辑时间线和成片。
- [screenplay-adapter](agents/screenplay-adapter/README.md)：剧本改编——把小说或大纲扩写、改编成可核对的场次剧本。

三者架构、实现和文档各自独立，不共享代码；边界见[仓库级决策](docs/decisions/proposed/architecture/2026-11-22-three-agent-subrepos.md)。

## 文档

- 协作规则：[AGENTS.md](AGENTS.md)
- 调研快照：[docs/research/](docs/research/)
- 仓库级/跨子 repo 决策：[docs/decisions/](docs/decisions/)

## 环境

Python 3.12+；视频相关子 repo 另需 `ffmpeg`/`ffprobe` 6.x。各子 repo 的命令和限制见自己的 README。
