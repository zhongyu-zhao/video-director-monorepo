# 视频 Agent 开源实践调研（2026-11）

**调研问题**：当前流行的 video agent 一般是怎么实现的？侧重有开源代码、可上手拆解的项目。

**范围**：以“从需求到成片”的完整链路为主，兼顾剪辑/后期 agent，并用视频理解 agent 做对照。
**数据快照**：2026-11-21，GitHub star 数只代表热度，不代表工程质量。

---

## 0. 一页结论

1. **“Video agent”不是一种东西。** 至少四种形态：端到端成片、剪辑/后期、通用制片 harness、视频理解/检索。它们的架构差异，大于“都叫 agent”这点共性。
2. **主流实现不是“一个万能 prompt 直接调视频模型”**，而是 **harness（运行时）+ 结构化中间态 + 工具 + 反馈闭环**。中间态通常就是剧本、分镜/镜头表、资产清单、时间线/EDL 这几层 JSON。
3. **控制流分三派**：代码 DAG（稳、可测、便宜）、LLM 编排（灵活、能处理开放需求）、混合（受约束 DAG + ReAct 兜底）。生产级项目基本都落在混合：**骨架用代码，决策点用模型**。
4. **体验分水岭是“可编辑性”。** 把时间线当唯一事实源、改一句字幕只重渲一个片段的项目（BaoCut、DiffusionStudio 这一类），才进得了真实工作流；一次性吐 MP4 的项目，第二次修改就要重来。
5. **最难的仍是长程一致性与成本。** 常见解法是参考图/角色三视图 + 首尾帧条件 + best-of-N + VLM 评审，再叠加 provider 评分、预算账本和缓存。这些工程手段，比换更强的视频模型更能决定成品率。

### 四种形态对照

| 形态 | 输入 → 输出 | 代表项目（star） | 核心难题 |
|---|---|---|---|
| 端到端成片 | 主题/剧本 → 一条成片 | MoneyPrinterTurbo（144.8k）、OpenMontage（81.9k）、ViMax（13k）、huobao-drama（17.8k）、Toonflow（22.4k） | 叙事结构、跨镜头一致性、成本 |
| 剪辑/后期 | 素材/长视频 → 时间线/成片 | video-use（31.3k）、BaoCut（1.8k）、FireRed-OpenStoryline（3.7k）、OpenCreator（14.4k）、AI-Youtube-Shorts-Generator（6.4k） | 理解素材、精确剪辑、可回退 |
| 制片 harness | 任意创作意图 → 调用工具完成 | OpenMontage、OpenEdit、OpenMotion、Crayotter | 编排、状态、质检、可追踪 |
| 理解/检索 | 视频 + 问题 → 答案/片段 | VideoAgent（2.1k）、DeepVideoDiscovery | 长视频检索、多粒度工具、上下文预算 |

---

## 1. 一般实现方式：一个 harness，五层

2026-10 的综述《Video Generation Meets Agent Harness》给了一个好用的定义：**harness 是围绕视频模型的可执行运行时，负责构造上下文、暴露工具、维护状态、路由反馈、管理预算**。开源项目虽然形态各异，但基本都能拆成这五层：

```
┌──────────────────────────────────────────────┐
│ 交互层   Chat / CLI / MCP / Agent Skill       │
├──────────────────────────────────────────────┤
│ 规划层   剧本、分镜、镜头表、任务 DAG、重规划   │
├──────────────────────────────────────────────┤
│ 工具层   生成、检索、TTS、剪辑、渲染、分析      │
├──────────────────────────────────────────────┤
│ 状态层   project.json / artifacts / checkpoint │
│          / 资产缓存 / 版本历史                  │
├──────────────────────────────────────────────┤
│ 治理层   schema 校验、质检、预算、人审、审计     │
└──────────────────────────────────────────────┘
```

下面按这五层拆具体做法。

### 1.1 阶段与工件：流水线的骨架

几乎所有“成片型”项目都收敛到同一组阶段：

```
研究 → 提案 → 剧本 → 分镜/镜头表 → 资产 → 剪辑 → 合成 → 发布
```

差别不在阶段名，而在**每个阶段是否产出结构化工件**。OpenMontage 是最典型的“工件驱动”：

| 阶段 | 产物（JSON） | 关键校验 |
|---|---|---|
| research | `research_brief` | ≥3 个数据点、≥5 条带 URL 的来源 |
| proposal | `proposal_packet` | 含预算与用户批准 |
| script | `script` | 与目标时长、旁白时长对齐 |
| scene_plan | `scene_plan` | 镜头意图、运动、转场 |
| assets | `asset_manifest` | provider、成本、来源 |
| edit | `edit_decisions` | 时间线决策 |
| compose | `render_report` | ffprobe、抽帧、音频 |

工件的作用有三个：**agent 之间的接口、人审的抓手、失败恢复的断点**。没有工件，长流程只能靠对话历史，一旦上下文超限就崩。

### 1.2 三种控制流，以及怎么选

**（A）代码 DAG / 状态机**
MoneyPrinterTurbo 的 `app/services/task.py` 是教科书：`script → terms → audio → subtitle → materials → video` 顺序执行，每一步更新 `state`、`progress` 和 `stage`，支持 `stop_at` 断点、失败标记、缓存复用。Crayotter 更进一步，用 LangGraph `StateGraph` + 确定性 scheduler，处理依赖校验、资源池、重试和写冲突。

- 优点：可预测、可测试、可恢复、token 便宜。
- 缺点：遇到开放需求不会变通。

**（B）LLM 编排（agent-as-director）**
OpenMontage 明确写“没有 code orchestrator，你的 coding agent 就是编排器”：每个 pipeline 是一份 YAML（阶段、工具、评审标准、成功条件），每个阶段是一份 Markdown “导演 skill”，agent 读完自己决定怎么做、何时送审、何时打回。`executive-producer` skill 里甚至维护了一个显式的 `EP_STATE`（预算、各阶段工件、旁白时长、风格锚点、返修次数）。

- 优点：能处理“我想要个像 xx 的视频”这类开放需求；加新 pipeline 只写文档。
- 缺点：不可复现、贵、容易“说做了但其实没做”（所以要有工具结果校验）。

**（C）混合**
Crayotter 先走受控的 editing DAG，结构化规划或校验失败才 fallback 到 ReAct editor；ViMax 同时提供直接 pipeline 入口和 Agent Loop/TUI。这是目前最务实的形态。

> 结论：**流程骨架用代码，创意决策和异常重规划用模型。** 纯 LLM 编排适合“个人助理”场景，不适合要稳定出片的产线。

### 1.3 工具层：统一契约 + 供应商解耦 + 评分选型

三个成熟做法：

1. **统一 tool 契约**。ViMax 的 `ToolSpec` 定义 `name / description / handler / aliases / permission_mode / schema / concurrency_safe`；OpenMontage 的 `BaseTool` 子类 + JSON Schema 注册表。这样 agent 看到的是同一套工具描述，换模型不用改 agent。
2. **能力与供应商解耦**。BaoCut 把 `transcribe / speak / generate image / generate text / separate audio` 定义成 capability，provider 可换本地模型或云 API；MoneyPrinterTurbo 的 LLM/TTS/素材/视频生成各有十几个 provider。
3. **评分选型而不是“第一个可用”**。OpenMontage 的 `lib/scoring.py` 按 7 维加权选 provider：任务匹配 30%、质量 20%、可控性 15%、可靠性 15%、性价比 10%、延迟 5%、连续性 5%，并把候选和得分写进决策日志。

配套的是**成本治理**：执行前 estimate、执行中 reserve、执行后 reconcile，支持 `observe / warn / cap` 三种模式，超过阈值（默认 $0.50/次）暂停等确认，总预算默认 $10。生成式视频按秒计费，没有这层，试错成本会失控。

### 1.4 状态：artifact-first、幂等、可恢复

- **工件即状态**：Crayotter 把检索报告、视频分析、剪辑蓝图、调度事件、工具调用、中间渲染都当 first-class artifact 落盘，前端可追踪、可诊断、可断点续跑。
- **幂等缓存**：ViMax 的角色抽取/定妆阶段先看 `characters.json`、`character_portraits_registry.json` 是否存在，存在就跳过；MoneyPrinterTurbo 复用未变更的渲染产物。
- **checkpoint + gate**：OpenMontage 的 `write_checkpoint` 会做 schema 校验，并拒绝“没记录人工批准却写成 completed”的 gated stage；被覆盖的 checkpoint 归档到 `history/`，保留审批轨迹。
- **版本化**：MoneyPrinterTurbo 的 video-project 支持场景级修改、版本比较、只重渲变化部分。

### 1.5 一致性：参考图 + 首尾帧 + best-of-N + 评审

跨镜头一致性是生成式视频的头号难题，开源项目的组合拳：

- **角色资产化**：ViMax 先抽角色、生成正面/侧面/背面三视图并注册；Toonflow 用角色三视图 + 场景资产库。
- **参考图条件**：每次生成都把角色/场景参考图带上，提示词里用 `@角色名` 映射（huobao-drama）。
- **首尾帧锁定**：OpenMontage 的产品片把已批准的 hero still 固定为首帧和尾帧，让模型只补中间运动，不破坏产品外形。
- **best-of-N + VLM 评审**：ViMax 一次生成多张候选，用 VLM 按“角色一致性 / 空间一致性 / 描述准确度”打分选最优（`best_image_selector.py` 里把评分维度写死在 system prompt）。
- **确定性预演**：Toonflow 先用 3D 白模排机位、走位、按台词切时间轴，再逐镜头生成——用 3D 把“镜头设计”变成确定输入，显著降低视频模型的不确定性。

### 1.6 质检：确定性检查 + VLM + 人审

成熟项目普遍是三层：

1. **结构校验**：JSON Schema 校验工件，不合格直接打回。
2. **确定性检查**：ffprobe 验时长/流，抽 4 帧查黑帧和坏 overlay，分析音频电平（静音/削波），检查字幕是否存在（OpenMontage 的 post-render self-review）；video-use 在成片每个切点跑 `timeline_view`，发现问题重渲，最多 3 次。
3. **风险评分与人审**：OpenMontage 有 slideshow risk 六维评分（重复、装饰性画面、运动弱、镜头意图、依赖排版、无依据的电影感声明）和 delivery promise 校验（承诺“motion-led”却 80% 静帧就 block）；proposal/script/scene/assets/publish 逐段人工确认。

### 1.7 可编辑性：时间线是唯一事实源

这是 2026 年最明显的分水岭。

- **BaoCut**：本地 Runtime + 桌面/CLI/MCP/skill 四个入口共用一套命令目录；agent 通过命令编辑而不是点击；每次修改返回 receipt，可 undo；渲染缓存按真实依赖失效，“改一句字幕只重渲一个片段”；人和 agent 共享同一个编辑器和 undo 栈。
- **DiffusionStudio**：工程就是一组 SolidJS JSX 文件，画布与代码双向同步，每个元素有 `id`，agent 改代码即改画面。
- **Cassette-Editor**（论文）：定义“人机共享的时间线语义”，一次 trim 会自动推导后续片段与字幕的联动，并有校验规则返回局部诊断。
- **FireRed-OpenStoryline**：对话式精修（剪/换/排序/样式），并把整套编辑流程存成可复用的 Skill。

对生成式流水线，**分镜/镜头表就是可编辑层**，渲染只是最后一步；只存最终 MP4 的项目，注定只能“重开一把”。

### 1.8 LLM 怎么“看”视频：文本优先，按需看图

video-use 的做法值得单独拎出来：它不逐帧喂模型，而是先用 ElevenLabs Scribe 出一份 word-level transcript（含说话人、笑声/掌声等音频事件），把整段素材压成 ~12KB 的 `takes_packed.md`；只有遇到模糊停顿、重拍比较、切点确认时，才生成一张 `timeline_view`（filmstrip + 波形 + 词标签）的图。

> 30,000 帧 × 1,500 token ≈ 45M token 的噪声；video-use 用 12KB 文本 + 几张图解决。

同理，OpenMontage 用 `scene_detect / frame_sampler / video_analyzer`，Crayotter 对每条素材做多模态分析后落成结构化报告。**这是视频 agent 最重要的 context 工程技巧**：先把视频变成可检索的文本/结构，再让模型按需看关键帧。

### 1.9 渲染与合成

- **Remotion（React）/ HyperFrames**：精确排版、动效、数据可视化、字幕动画，代码即模板。
- **FFmpeg filter graph**：纯剪辑、拼接、混音、烧字幕，快且便宜。
- **HTML → 帧**：OpenMotion 用“code video with HTML”，agent 复刻参考片的镜头与转场。
- **3D（Blender）**：需要真实相机运动和物理时。

选择标准是“视觉语法”：排版/动效重就用 Remotion/HTML，素材剪辑重就用 FFmpeg，不要拿一种渲染器硬套所有片子。

---

## 2. 代表项目拆解

### OpenMontage（81.9k，AGPL-3.0）

- **定位**：agent-first 的全流程制片系统，把 Claude Code / Cursor / Codex 变成“制片厂”。
- **实现**：`pipeline_defs/*.yaml`（阶段/工具/评审标准/成功条件）+ `skills/`（每阶段一个 director skill + reviewer/checkpoint 等 meta skill）+ `tools/`（100+ BaseTool）+ `lib/`（checkpoint、scoring、delivery_promise、slideshow_risk）+ Remotion/FFmpeg 渲染。Python 只提供工具和持久化，编排与创意判断都在 Markdown 里。
- **值得抄**：工件 schema、人审 gate、7 维选型、决策日志、预算控制、slideshow 风险评分。
- **局限**：强依赖 coding agent；AGPL；700+ skill 文件维护成本高；质量取决于所用模型。

### MoneyPrinterTurbo（144.8k，MIT）

- **定位**：主题/关键词 → 口播短视频，工程完整度最高的“确定性流水线”。
- **实现**：FastAPI + WebUI/CLI/API；`task.py` 串起 script→terms→audio→subtitle→materials→video，state + progress + stop_at 支持断点与恢复；素材来自 Pexels/Pixabay/Coverr/本地/AI 视频；TTS 十几家；字幕用 TTS 时间戳或 Whisper；FFmpeg/MoviePy 合成；支持批量、任务历史、项目版本、跨平台发布。
- **值得抄**：任务状态机、失败重试、素材缓存、provider 适配层——一个能跑住的生产流水线长什么样。
- **局限**：模板化，创意控制弱；不是 agent，更像 workflow。

### ViMax（13k，MIT）

- **定位**：叙事驱动的多镜头生成（Idea2Video / Script2Video / Novel2Video）。
- **实现**：Python pipeline + 专职 agent：`script_planner`、`screenwriter`、`script_enhancer`、`character_extractor`、`character_portraits_generator`、`storyboard_artist`、`camera_image_generator`、`reference_image_selector`、`best_image_selector`；领域模型齐全（Character/Scene/Event/Camera/Frame/ShotDescription/ImageOutput/VideoOutput，全部 Pydantic）；每阶段落盘幂等；best-of-N 由 VLM 选图；另有 `agent_runtime` 提供 loop/tools/session/context compaction。
- **值得抄**：角色一致性链路、领域本体、并行生成、resume。
- **局限**：重资产、成本高；长片仍是镜头拼接。

### huobao-drama（17.8k）

- **定位**：一句话 → 短剧成片。
- **实现**：Hono + Drizzle + SQLite + Mastra；4 个 Mastra agent（`script_rewriter`、`extractor`、`storyboard_breaker`、`prompt_generator`）；agent skill 放在 `backend/workspace/skills`，可在界面在线编辑；模型与 prompt 走数据库配置。
- **值得抄**：把 prompt/skill 当“运营资产”而不是代码，非技术人员可迭代；短剧阶段切分干净。
- **局限**：一致性主要靠参考图 + prompt；成片质量受第三方视频模型限制。

### Toonflow（22.4k，MIT）

- **定位**：短剧/漫剧，无限画布式创作。
- **实现**：无限画布 + 角色三视图 + 场景资产 + **3D 白模预演**（一键搭景、排机位、走位、按台词切时间轴）+ 逐镜头生成 + 时间线剪辑；MCP/插件扩展。
- **值得抄**：用 3D previs 把“镜头设计”前置成确定性输入；资产复用。
- **局限**：学习曲线陡；3D 预演本身是重活。

### video-use（31.3k，MIT）

- **定位**：给 coding agent 的剪辑 skill：丢素材 → 对话 → `final.mp4`。
- **实现**：`SKILL.md` + `helpers/` 脚本 + ffmpeg；ElevenLabs Scribe 转写 → `takes_packed.md` → LLM 产出 EDL → 渲染 → 每个切点 `timeline_view` 自检（最多重渲 3 次）→ `project.md` 记忆。
- **值得抄**：文本优先的视频理解、先策略确认再动手、自评闭环、12 条硬规则（生产正确性不可协商，审美自由）。
- **局限**：以口播/素材剪辑为主，不生成画面。

### BaoCut（1.8k）

- **定位**：“为 agent 而生的视频编辑器”。
- **实现**：本地 Runtime + 桌面/CLI/MCP/skill 四入口共用工具目录；命令式编辑（非点击）；时间线承载字幕/翻译/配音/章节/动效；事务 + undo + receipt；渲染缓存按依赖失效；bounded autonomy（scope/access/budget/approval）。
- **值得抄**：可编辑性与人机协作的天花板；“改一处只改一处”的工程实现。
- **局限**：桌面应用偏重；star 少但设计成熟。

### FireRed-OpenStoryline（3.7k，Apache-2.0）

- **定位**：自然语言驱动的成片/剪辑。
- **实现**：媒体搜索下载 + 内容理解、脚本生成（few-shot 风格迁移）、BGM/TTS/字体推荐、对话式精修、编辑 Skill 归档复用、ASR 粗剪（去口癖/重复句）。
- **值得抄**：Style Skill 复用、对话式迭代、企业级工程完整度。
- **局限**：依赖云服务；效果受素材质量影响。

### Crayotter（256，PolyForm 非商用）

- **定位**：长视频剪辑的多 agent 系统（AACL 2026 Demo）。
- **实现**：LangGraph `StateGraph` 三阶段——planner + 确定性 scheduler（依赖 DAG、资源池、重试、写冲突）→ editing research（纯推理，产出剪辑蓝图）→ ReAct editor（受控 DAG + fallback）；检索/下载/分析/剪辑/转场/旁白/字幕/导出全工具化；全链路 artifact 可观测、可断点恢复。
- **值得抄**：可追踪、可诊断、可恢复；“先研究再动手”；调度器处理并发与冲突。
- **局限**：非商用 license；偏剪辑而非生成；demo 属性强。

### Director（1.6k，MIT）

- **定位**：video agent 框架（VideoDB 生态）。
- **实现**：reasoning engine + 20+ 预置 agent（摘要/搜索/剪辑/配音/翻译……）+ chat UI + player，事件流式输出。
- **值得抄**：把视频当“数据”（索引、检索、流式）而不是文件处理；agent 编排框架化。
- **局限**：绑定 VideoDB 云服务。

### 理解侧：VideoAgent（2.1k，EMNLP 2026）与 Deep Video Discovery（NeurIPS 2025）

共同套路：把长视频切段当“探索环境”，给模型多粒度工具（全局摘要/片段检索/帧采样/字幕），让模型迭代地“观察—反思—再看”。DVD 的 lite mode 只用字幕也能跑播客类视频。这类能力是剪辑 agent 的前置。

---

## 3. 共性坑

1. **star ≠ 可用。** 大量 2026 年新项目是 demo：issue 多、维护周期短、文档漂亮但跑不通。选型要看最近 3 个月 commit 和 issue 响应。
2. **许可证。** OpenMontage 是 AGPL-3.0，Crayotter 是 PolyForm 非商用；商用集成前必须确认。多数项目 MIT/Apache-2.0。
3. **一致性仍是瓶颈。** 跨镜头角色/风格靠参考图 + 选片，长片本质仍是“拼接”；没有项目真正解决小时级叙事的连贯。
4. **成本。** 生成模型按秒计费，试错成本高；没有 estimate/cap/缓存的项目，跑几条就烧穿。
5. **评测缺失。** 多数只有 demo 视频，缺可复现 benchmark；AgenticVBench 刚起步，Crayotter 的 23 主题人工评分（3.40/5）已算认真。
6. **一次性 MP4 vs 可编辑时间线。** 后者工程量大 3–5 倍，但决定能否进真实工作流。
7. **provider 变化快。** 抽象层是刚需，硬编码单一 API 的项目半年就废。

---

## 4. 如果要做 video director agent：一个可落地的参考架构

结合上面的共性，建议的顺序是“**先确定性内核，再 agent 外壳**”：

**M0 内核（不依赖 LLM）**
- 领域模型：`Project → Scene → Shot → Asset → TimelineClip → Revision`
- 渲染：FFmpeg filter graph + EDL，先做到“同一输入必得同一输出”
- 项目存储：JSON 工件 + 资产目录 + 版本历史

**M1 工具层**
- 统一 `ToolSpec`（name / JSON Schema / permission / concurrency / cost）
- provider adapter（生成、TTS、素材、分析各一组）
- 成本账本：estimate → reserve → reconcile，带 cap

**M2 编排**
- 代码 DAG 管阶段（script → shotlist → assets → edit → compose）
- 每阶段：读 manifest → 调工具 → 产物过 schema → checkpoint
- LLM 只负责阶段内的创意决策与失败重规划

**M3 反馈**
- 确定性 QC（ffprobe/抽帧/音频/字幕）
- VLM 评审（一致性、构图、可看性）
- 人审 gate（提案/剧本/分镜/资产/成片）

**M4 skill 化**
- 把每类视频的 know-how 写成 manifest + skill（OpenMontage 路线），便于扩 pipeline
- 把成功的编辑流程存成可复用 Style Skill（FireRed 路线）

一个最小但完整的目录结构：

```
project/
  project.json          # 元信息、预算、状态
  artifacts/
    research_brief.json
    script.json
    scene_plan.json
    asset_manifest.json
    edit_decisions.json
  assets/               # 生成的/下载的素材
  renders/              # 中间渲染与最终成片
  history/              # checkpoint 归档
```

---

## 5. 参考资料

### 开源项目

| 项目 | Star | License | 一句话 |
|---|---|---|---|
| [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) | 144.8k | MIT | 主题→口播短视频的确定性流水线 |
| [OpenMontage](https://github.com/OpenMontageInc/OpenMontage) | 81.9k | AGPL-3.0 | agent-first 全流程制片 harness |
| [video-use](https://github.com/browser-use/video-use) | 31.3k | MIT | 给 coding agent 的剪辑 skill |
| [Toonflow](https://github.com/HBAI-Ltd/Toonflow-app) | 22.4k | MIT | 短剧/漫剧 + 3D 白模预演 |
| [huobao-drama](https://github.com/chatfire-AI/huobao-drama) | 17.8k | 未声明 | 一句话短剧，Mastra 多 agent |
| [OpenCreator](https://github.com/krillinai/OpenCreator) | 14.4k | Apache-2.0 | 翻译/配音/创作 workspace |
| [OpenMotion](https://github.com/nexu-io/openmotion) | 13.8k | Apache-2.0 | HTML 代码化视频 + 参考片复刻 |
| [ViMax](https://github.com/HKUDS/ViMax) | 13.0k | MIT | 叙事驱动的多镜头生成 |
| [AI-Youtube-Shorts-Generator](https://github.com/Anil-matcha/AI-Youtube-Shorts-Generator) | 6.4k | MIT | 长视频→爆款切片 |
| [FireRed-OpenStoryline](https://github.com/FireRedTeam/FireRed-OpenStoryline) | 3.7k | Apache-2.0 | 对话式成片/剪辑 |
| [DiffusionStudio](https://github.com/diffusionstudio/editor) | 3.5k | MPL-2.0 | 代码即工程的 agent 编辑器 |
| [VideoAgent](https://github.com/HKUDS/VideoAgent) | 2.1k | — | 理解/编辑/重制一体的 agent |
| [BaoCut](https://github.com/JimLiu/baocut) | 1.8k | 未声明 | 命令式、可 undo 的 agent 编辑器 |
| [OpenEdit](https://github.com/veedstudio/open-edit) | 1.8k | — | 无时间线、agent 写页面即视频 |
| [Director](https://github.com/video-db/Director) | 1.6k | MIT | VideoDB 的 video agent 框架 |
| [Crayotter](https://github.com/idwts/Crayotter) | 256 | PolyForm NC | 可追踪的长视频多 agent 剪辑 |
| [DeepVideoDiscovery](https://github.com/microsoft/DeepVideoDiscovery) | — | MIT | 长视频深度研究式问答 |

### 论文与综述

- [Video Generation Meets Agent Harness](https://arxiv.org/abs/2610.40191)（2026-10，agentic video generation 综述，“harness”定义的来源）
- [ViMax 技术报告](https://arxiv.org/abs/2606.07649)
- [Crayotter: Traceable Multi-Agent Workflows for Long-Form Video Editing](https://arxiv.org/abs/2606.07636)
- [Cassette-Editor: Shared Timeline Semantics for Human and Agent Editing](https://arxiv.org/abs/2610.37690)
- [AgenticVBench: Can AI Agents Complete Real-World Video Production Tasks?](https://neurips.cc/virtual/2026/loc/sydney/poster/139672)
- [Deep Video Discovery](https://arxiv.org/abs/2505.18079)
- [Awesome Agentic Video Generation](https://github.com/agentic-videogen/awesome-agentic-videogen)（387 篇论文的资源库）

---

*调研方法：GitHub API 取 2026-11-21 的 star/license 快照；通读 17 个项目的 README，并实际拉取 OpenMontage、ViMax、MoneyPrinterTurbo 的代码结构做交叉验证；论文与综述以 arXiv 摘要为准。项目描述以 README 与代码结构为准，未逐一实跑。*
