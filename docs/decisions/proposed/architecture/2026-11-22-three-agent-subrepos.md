# 决策：第三个并列子 repo——小说扩写 / 改编

状态：proposed

## 问题

仓库已有两个并列子 repo：`auto-shot`（自动拉片）和 `video-director`（视频制作）。现在要新增第三个能力：把现有小说或故事大纲扩写、改编成可拍摄的视频剧本。

它和另外两个子 repo 的输入、工件、运行方式和质量门都不同：

- `auto-shot` 从成片反推镜头和剧本分析，输入是视频；
- `video-director` 从创作意图到时间线/成片，输入是素材和剪辑意图；
- 剧本改编的输入是长文本，核心问题是选择、压缩/扩写、场景化和人物一致性。

需要决定：它是否作为第三个独立子 repo、如何与另外两个交换数据、当前阶段做到什么程度。

## 决定

1. **新增第三个自包含子 repo**：`agents/screenplay-adapter/`。与另外两个并列，不共享 Python 包、不互相 import，架构/文档/测试各自独立。
2. **沿用版本化 JSON 交换**：本项目输出 `screenplay.json` + Fountain/Markdown；video-director 可以按自己的契约消费剧本/场次，但不共享内部类型。auto-shot 的 `screenplay.json` 是从成片反推的分析产物，schema 不同，不共享。
3. **独立开发线**：后续变更走独立分支和 PR，标题带 `screenplay-adapter:` scope。跨子 repo 的决策变更除外；本 PR 是引导例外，只做新子 repo 的调研、ADR、骨架和首个纵切。
4. **仓库边界原则不变**：根 `docs/` 只放仓库级决策；子 repo 的架构、路线图、契约和决策在自己的 `docs/` 下；根 `AGENTS.md` 只写全局规则和三个子 repo 的入口。
5. **可拆分**：`agents/screenplay-adapter/` 自包含，未来需要独立仓库时用 `git subtree split` 搬走，不改代码或文档结构。
6. **首个纵切（M0）**：确定性改编计划（章节/句子 → 人物 → 场次/来源/时长/节拍）+ OpenAI 兼容的逐场写作 + 合并导出 + 验收门。人物状态机、因果情节图、自动改写和 UI 留给后续 PR。

## 备选方案

- **作为 video-director 的一个模块**：能复用项目/时间线，但会把“文本改编”的 schema、prompt、测试和节奏绑到渲染内核上；两边演化速度不同，否决。
- **作为 auto-shot 的第二个方向**：auto-shot 的核心是视频理解，改编是文本生成；共享只会让两边的 schema 和测试互相污染，否决。
- **单独 GitHub 仓库**：边界最硬，但当前是单人 + agent 的节奏，多仓 issue/PR/CI/权限是额外开销；先同仓并列，等有独立发布/权限需求再拆。
- **先做 UI**：没有稳定计划和 schema 时 UI 会返工；先 CLI + 工件。
- **先接视频生成/分镜**：改编质量还没验证，过早接下游会把问题掩盖在渲染里；先做计划和剧本门。

## 后果

- 根目录多一个 `agents/screenplay-adapter/`；初次进入需要读子目录 `README.md` 和 `AGENTS.md`。
- 三个子 repo 都只依赖 Python 3.12+，但 screenplay-adapter 不需要 ffmpeg；CI 可以按子 repo 分别跑。
- 跨 agent 的契约需要显式版本化；下游不能假设 `screenplay.json` 的字段永远不变。
- 改编质量仍需要人读；M0 的门只保证结构、覆盖、人物和格式，不保证“好看”。
