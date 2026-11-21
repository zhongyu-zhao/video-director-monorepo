# 决策：两个 agent 子 repo 的仓库形态与边界

状态：proposed

## 问题

本仓库要同时承载两个 agent：自动拉片（auto-shot）和视频制作（video-director）。两者的输入、工件、运行方式、模型成本和演进节奏都不同。如果共享目录、共享包或共享文档，任何一方的 schema、prompt、依赖或版本变更都会耦合到另一方。仓库所有者要求二者“架构设计和实现以及文档体系都独立”，并希望分两个分支开发。

需要决定：子 repo 在 Git 里是什么形态，二者共享什么、不共享什么，以及未来如何拆开。

## 决定

1. **一个 Git 仓库，两个自包含子 repo**：`agents/auto-shot/` 与 `agents/video-director/`。本阶段不引入 git submodule，也不拆成两个独立 GitHub 仓库。
2. **代码不共享**：两边不互相 import，不建共享 Python 包。跨 agent 的数据交换只走版本化 JSON 文件：例如 auto-shot 导出的 `shots.json` 可以作为 video-director 的镜头表输入，但由消费方按自己的契约校验，不共享内部模型。
3. **文档不共享**：根 `docs/` 只放仓库级、跨子 repo 的决策；每个子 repo 的架构、路线图、数据契约和决策都在自己的 `docs/` 下。根 `AGENTS.md` 只写全局规则和两个子 repo 的命令入口，子目录 `AGENTS.md` 写各自规则。
4. **独立开发线**：后续每个子 repo 的变更走独立分支和 PR，一个 PR 只动一个子 repo（跨子 repo 的决策变更除外），提交标题带 `auto-shot:` 或 `video-director:` scope。本 PR 是例外：只做两个子 repo 的骨架、首个纵切和仓库级 ADR。
5. **可拆分**：每个子目录自包含。未来若需要独立仓库或独立发布节奏，用 `git subtree split` 搬走即可，不需要改代码或文档结构；在此之前不付 submodule 和多仓同步的成本。
6. **只共享仓库级设施**：根 `LICENSE`、根 `AGENTS.md`、根 `README.md`，以及未来的 CI 矩阵。CI 分别跑两个子 repo 的检查，不做跨项目耦合。

## 备选方案

- **git submodule / 两个独立 GitHub 仓库**：边界最硬，但当前是单人 + agent 的节奏，双仓 issue、PR、CI、权限和版本对齐都是额外开销，且本阶段没有独立发布或权限隔离需求。等出现外部使用方或独立 release 节奏时再拆。
- **单包多模块**：一个 `pyproject.toml` 下放两个包。共享方便，但与“架构和文档独立”冲突，依赖和测试也会互相污染。
- **每个 agent 一个长期分支、不合并**：分支会漂移，文档和主干脱节；分支只作为短期开发线，不作为长期形态。

## 后果

- 根目录多一个 `agents/` 容器；每个子 repo 有自己的命令和文档入口，初次进入需要读子目录的 `AGENTS.md`。
- 跨 agent 的数据契约必须显式版本化并校验，不能靠共享类型“顺手”传递。
- 两边可以独立选技术栈。当前都选 Python 3.12+，但 video-director 未来引入 TypeScript/Remotion 渲染器时不影响 auto-shot。
- 拆成独立仓库是机械操作，不是重写；代价是拆之前两个子 repo 仍共享同一个 PR 权限和 CI 流水线。
