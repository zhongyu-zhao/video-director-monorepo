# 工业级电影/动画制作管线调研（2026-11）

**调研问题**：做短剧或 AI 视频时，如何像真实的电影/动画制作一样，用设定集、剧本、分镜表、分镜简图逐级约束每个镜头的提示词，减少返工？现有的工业级管线是怎么组织这些工件的？

**范围**：真人电影、美国三维动画、日本 TV/剧场动画、中国动画电影工业化、AI 原生短剧/视频五类管线；重点是从剧本到镜头生成之间的工件链、字段、评审门和版本管理，不展开拍摄现场管理、后期调色和混音的具体工艺。

**数据快照**：2026-11-26。资料来自公开的行业访谈、厂商文档、标准文档和开源项目；未接触任何工作室内部管线，AI 厂商文档变化很快，引用时以文末日期为准。

**术语约定**：本文把“设定集”对应到 animation bible / series bible / settei，“剧本”对应 screenplay，“分镜表”对应镜头级表格规格（storyboard table / shot list / e-conte 的文字与时间栏），“分镜简图”对应 thumbnail / rough board，“镜头提示词”对应 shot prompt。日本动画的 e-conte 是“表 + 图”合一的典型：同一页既有构图缩略图，也有 cut 号、动作、台词、秒+帧。数字管线可以把它们拆成 shot table 和 board image，但必须用同一个 `shot_id` 绑定；否则表和图会各说各话。不同工作室的叫法不完全一样，重要的是每层锁住什么。

---

## 0. 一页结论

1. **工业级不等于“文档多”，而是“同一批 ID 在多道门之间流转”。** 剧本、分镜、镜头表、提示词不是四份互相抄写的文档，而是同一组 scene/shot/asset ID 的不同视图；真正的事实源是制作数据库（ShotGrid、ftrack、Kitsu 这一类）和工作文件，不是某一版 PDF。
2. **每层工件锁不同的自由度。** 设定集锁“长什么样”，剧本锁“发生什么、谁说什么”，分镜锁“怎么拍、多久”，镜头表锁“现场/生成的执行参数”，提示词只是最后一层编译产物。上游没锁住的东西，下游一定会在生成时重新发明。
3. **最便宜的试错层是 story reel / animatic / e-conte，而不是拍摄或生成。** 动画和 AI 视频的共同点是“做出来很贵、改起来更贵”，所以工业管线把大量时间花在动态分镜上：用简图、时间、临时对白和音乐先看整片，再决定哪些镜头值得进入昂贵工序。
4. **分镜简图是契约，不是插画。** 它同时规定构图、景别、机位、调度、视线、轴线、时长和声音落点。日本动画的 e-conte 把这一点做到极致：cut 号、画面、动作、台词/SFX、秒+帧、bleed 都是施工字段，缺一个下游就要猜。
5. **日本 e-conte 是最接近“镜头提示词表”的工业模板。** 它不写“氛围感”，而写“从哪看、看什么、持续多久、听到什么”；一个 cut 就是一个可排期、可计价、可交接的工作单元。这个结构可以直接映射到 AI 生成的 shot spec。
6. **AI 原生管线把“分镜→提示词”压成一步，但没有省掉设定集和镜头表。** 实践者仍然先做角色转面图、场景参考、道具参考，再把剧本拆成 2–3 秒的 beat，一条 beat 一条提示词；区别只是“画”变成了“生成 + 筛选”。
7. **一致性靠“参考资产 + 结构化镜头状态 + 版本/审批”，不靠 prompt 文采。** 参考图锁定外观，镜头状态锁定位置/朝向/光线/轴线，版本和审批锁定“这一条到底用哪次生成”。只堆形容词的 prompt，换一个镜头就会漂移。
8. **对短剧，工件要减量但不能缺层。** 短剧可以没有电影级 previz，也可以没有全片精修分镜，但设定锚点、场次/镜头表、时长、连续性、参考资产这几层不能省；省掉哪一层，返工就会在那一层爆发。
9. **对本仓库，M2 应先做“可核对的镜头表 + 简图 + 时长/连续性门 + 提示词编译”，再做生成。** `project.json` 继续做时间线事实源；新增 `bible.json`、`storyboard.json`、`prompt_sheet.json` 作为上游规划工件；prompt 是编译视图，不是第二份事实。

### 五类管线速查

| 管线 | 核心中间态 | 最便宜的试错门 | 关键决定者 | 对“镜头提示词”的启示 |
|---|---|---|---|---|
| 真人电影 | shooting script + shot list + previz | 分镜/previz/techvis | 导演、摄影指导、第一副导演 | 提示词字段来自 shot list：景别、角度、运动、镜头、主体、VFX、设备 |
| 美国三维动画 | story reel + color script + layout | story reel / editorial | 导演、head of story、剪辑 | 先把板子剪成 animatic，再让生成/动画去填 |
| 日本 TV/剧场动画 | e-conte + layout + timesheet | e-conte / animatic | 导演、演出、作画监督 | cut 号、秒+帧、画面、台词/SFX、bleed 是硬字段 |
| 中国动画电影 | 分镜 + 概念设计 + 资产 + 跨公司协作 | 分镜/动态故事板 | 导演、分镜师、制片/后期管理 | 分镜是跨供应商“图纸”，变更必须可追踪 |
| AI 原生短剧/视频 | shot list + 参考资产 + prompt | 首帧/样片/小批量抽卡 | 导演/制片、prompt 设计者 | 一条 beat 一条 prompt；immutable/mutable 分层；参考图+首尾帧+seed |

### 从设定集到提示词：一张映射表

| 阶段 | 工业工件 | 锁定的内容 | 本仓库候选工件 | 下游用途 |
|---|---|---|---|---|
| 设定集 | animation bible、model sheet、color script、settei | 角色外观、场景、道具、色板、风格、锁定锚文本 | `bible.json` + 参考图 | 提示词的 immutable 段、参考资产、评审基准 |
| 剧本 | screenplay、shooting script、script breakdown | 场次、beat、动作、对白、制作元素 | `screenplay.json` + `bible.json` 的资产 cast | 镜头覆盖、对白、资产引用 |
| 分镜表 | shot list、e-conte 的时间/动作栏 | 镜号、时长、景别、角度、镜头、运动、声音、连续性 | `storyboard.json` 的 shots | 编译 prompt 的 mutable 段、animatic |
| 分镜简图 | thumbnail、storyboard panel、e-conte 的画面栏 | 构图、调度、轴线、视线、bleed | `board.image` + staging | 首帧/参考图、构图评审 |
| 镜头提示词 | shot prompt、generation params | 模型、prompt、refs、seed、negative、provenance | `prompt_sheet.json` | 生成任务、复现、评审 |

这张表的用法是反过来的：**先问“这个字段由哪一层锁”，再决定它写进哪个工件。** 如果外观写在镜头表里，设定集就失效了；如果时长写在 prompt 里，animatic 就失效了；如果参考资产只写在 prompt 文本里，生成器就无法稳定解析。

相关调研：短剧的体量、分集和卡点规则见 [小说扩写/改编为视频剧本调研](2026-11-novel-to-screenplay-survey.md)；从成片反推镜头和剧本见 [自动拉片调研](2026-11-auto-shot-analysis-survey.md)；video agent 的开源实现见 [视频 Agent 调研](2026-11-video-agents-survey.md)。本文不重复这些内容，只补“从设定集到镜头提示词”这一段。

---

## 1. “工业级”的共同点：分工、标准、版本、门

“工业级”经常被误解成“预算高、软件贵”。从公开资料看，更准确的定义是四件事：

**第一，分工与交接。** 《哪吒 2》144 分钟、5 年半、138 家中国动画公司、4000 多名动画人参与；前期分镜和概念设计结束后，交付给模型、动画、场景、特效、灯光合成、配音等中期部门同步制作（[网易/新京报](https://m.163.com/dy/article/JPPTLBB40512D3VJ.html)）。如果没有统一的镜头编号、资产命名和版本，这种协作无法开始。

**第二，标准字段。** 日本动画的 e-conte 有相对固定的栏目，换一个工作室的板子，动画师也知道去哪一栏找 cut 号、时间、台词（[ScreenWeaver](https://www.screenweaver.ai/blog/anime-storyboard-e-konte)）。真人电影的 shot list 也有相对稳定的字段：场号、镜号、描述、景别、角度、运动、主体、VFX、机身、设备、镜头（[StudioBinder](https://www.studiobinder.com/blog/shot-list-template-free-download/)）。标准字段的价值不是好看，而是让不同部门在同一张表上签字。

**第三，版本与评审。** DreamWorks 的故事部门用 Flix 管理分镜迭代：每次修改按时间顺序保存，重排时自动重编号，评审可以快速拼装，版本自动归档（[Foundry](https://colorway.foundry.com/ja/insights/film-tv/how-to-train-your-dragon-flix)）。Pixar 的剪辑部门被描述为“轮子的轴心”，从 story reel 阶段就介入，把各环节连起来（[Cartoon Brew](https://www.cartoonbrew.com/books/making-the-cut-pixar-kinder-osteen-218914.html)）。

**第四，成本可归因。** 动画的预算可以细到帧：e-conte 的时间栏是“秒+帧”，一个 cut 的时长是承诺，不是建议；动画师悄悄拉长一个 cut，会打乱整集的工时和预算（[ScreenWeaver](https://www.screenweaver.ai/blog/anime-storyboard-e-konte)）。AI 短剧同样按条计价：按报道中的高端模型价格，一条 15 秒视频大约 20 元，100 分钟正片约 400 条 15 秒素材，抽卡是最耗时、最花钱的环节（[中国之声/搜狐](https://m.sohu.com/a/1016209326_362042/)）。

这四点合起来，就是一条“工件链 + 资产库 + 评审门”的管线。下面按类型拆。

---

## 2. 真人电影：镜头表是通用语言，分镜是复杂镜头的专用语言

### 2.1 阶段与工件

| 阶段 | 典型工件 | 锁定的东西 | 典型门 |
|---|---|---|---|
| 开发 | logline、treatment、screenplay | 故事、人物、结构、调性 | greenlight |
| 前期 | shooting script、script breakdown、production board、shot list、storyboard、previz/techvis | 可执行计划、预算、调度、镜头设计 | 导演/摄影/第一副导演确认 |
| 拍摄 | call sheet、camera report、continuity、dailies | 现场执行与素材 | 每日样片 |
| 后期 | EDL/AAF/XML、VFX turnover、postvis | 剪辑、视效交接、最终画面 | picture lock |

真人电影的“剧本”不是小说，而是可分解的拍摄文件。Fountain 这类纯文本格式把场景头、动作、角色、对白、转场、分节/梗概都写成可解析的标记，场号可以显式标注（[Fountain](https://fountain.io/syntax/)）。这让“剧本→场次→镜头”的自动分解成为可能。

### 2.2 从剧本到镜头表：script breakdown 是关键中间步

Script breakdown 是把剧本拆成制作元素的列表：演员、群演、道具、服装、特殊效果、车辆、动物、音效、特技等；行业用颜色标记不同元素，再汇总成 production board、拍摄计划和预算（[Script breakdown](https://en.wikipedia.org/wiki/Script_breakdown)）。Production board 的每条 strip 通常包含场号、日/夜、页数（八分之一页）、布景、实景地、出场人物和备注（[Production board](https://en.wikipedia.org/wiki/Production_board)）。

这一步对 AI 管线的启示很直接：**“这个镜头里有哪些资产”不是生成时现想，而是从剧本分解和资产表里 cast 出来的。** 角色、场景、道具在进入镜头之前就应该有 ID 和参考图；镜头表只引用 ID，不重复描述外观。

Shot list 则是镜头级的执行表。StudioBinder 的字段可以作为最小集：场号、镜号、描述、景别、镜头类型/角度、摄影机运动、状态、主体、VFX、机身、设备、镜头（[StudioBinder](https://www.studiobinder.com/blog/shot-list-template-free-download/)）。这些字段和 AI 视频提示词有很高的重合度：景别、角度、运动、镜头、主体，本来就是提示词要写的东西。区别是 shot list 还带现场执行信息（设备、机身、VFX），提示词则要带模型参数和参考资产。

### 2.3 分镜在真人电影里是“选择性”的

真人电影并不是每一场都画分镜。分镜通常用于动作、特技、VFX、复杂调度或广告；普通文戏靠 shot list 和现场调度。分镜帧会标注箭头、摄影机运动、画幅比例，作用是在开机前发现构图和调度问题（[Storyboard](https://en.wikipedia.org/wiki/Storyboard)）。

但 AI 视频不一样：**每一个镜头都是“生成”的，所以每一个镜头都需要某种程度的分镜。** 不一定是精细的画家板，可以是一张构图草图、一张参考图、一张首帧，甚至是一段文字加一张空间站位图。关键是它要能回答“从哪看、看什么、主体在哪、光线从哪来”，而不是只有一句“两个人在房间里对峙”。

### 2.4 视觉预览的三层：previs、techvis、postvis

好莱坞把预览拆成三层：

- **Previs（视觉预览）**：用简化的 3D 或动态分镜，在正式拍摄前展示走位、取景、摄影机角度和运动，用来做创作决策；可以带临时音乐、音效和对白（[Previsualization](https://en.wikipedia.org/wiki/Previsualization)）。
- **Techvis（技术预览）**：把预演落到真实物理条件：镜头焦距、轨道长度、摇臂高度、布景尺寸、安全约束。它回答“这个镜头在拍摄日能不能做到”（[Runway: AI previs](https://runway.com/resources/ai-previs)）。
- **Postvis（后期预览）**：把实拍素材和临时特效合在一起，让剪辑在最终 VFX 完成前就能看节奏（同上）。

《流浪地球》是一个中国案例：重场戏用了 PreViz，其余文戏和过场戏用动态故事板，剪满了 160 分钟动态故事板；粗剪阶段有 4000 多个视效镜头，最终留下约 2200 个；后期管理强调素材出入流程、水印标准、分包和进度跟踪（[中国电影报](https://chinafilmnews.cn/Html/2019-02-28/799.html)）。

Runway 对 AI previs 的边界说得很清楚：生成模型能把“这场戏成不成立”的探索做快，但生成帧没有可测量的 3D 空间，不能替代 techvis；镜头之间精确的空间连续性也不会自动保持（[Runway: AI previs](https://runway.com/resources/ai-previs)）。这对 AI 短剧的含义是：**AI 可以替代“画出来看”的一部分，但不能替代“把空间和时长定死”的那一部分。**

### 2.5 对本项目的启示

- Shot list 是最小可用 schema；即使不做分镜绘制，也应该先有镜头表。
- Script breakdown 应该成为“资产 cast 到镜头”的步骤：每个镜头引用角色/场景/道具 ID，而不是重复描述。
- 真人电影可以只给复杂镜头画分镜；AI 视频需要每个镜头都有视觉锚点，但锚点可以是粗图/首帧/站位图，不必是精绘。
- Previs/techvis 的区分值得保留：创作预演可以生成，物理/空间校验不能假装生成。

---

## 3. 美国三维动画：story reel 是“第一版电影”

### 3.1 阶段

| 阶段 | 典型产物 | 作用 |
|---|---|---|
| 开发 | pitch、treatment、script | 故事和绿灯 |
| 视觉开发 | 角色/场景/道具设计、model sheet、color script、style guide | 锁定“长什么样” |
| 故事 | beat board、storyboard、story reel | 锁定“怎么讲、怎么切、多久” |
| 模型/绑定 | 3D 模型、材质、骨骼 | 把设计变成可动画资产 |
| Layout | 相机、构图、走位、粗场景 | 把 board 变成 3D 空间里的镜头 |
| 动画 | 表演、动作、表情 | 把表演做出来 |
| 灯光/合成/渲染 | 最终画面 | 把镜头做成成片 |

### 3.2 设定集：不是“人物小传”，是生产标准

法国 SACD 对 animation bible 的定义可以作为参考：它是动画剧集的“原始和奠基性参考文件”，定义并描述不同作者写分集时需要的元素，包括概念、类型、格式和目标受众、主要和次要角色及其关系、角色的发展线索、地点、剧集的基调/氛围/风格、叙事机制（[SACD](https://www.sacd.fr/sites/default/files/bulletin_declaration_crea_serie_def_bible_en.pdf)）。这是“剧集设定集”，不是单部电影的美术设定，但结构相通。

在三维动画里，设定集至少包括：

- **Model sheet（模型表/转面图）**：正面、侧面、背面、3/4 视角，加上手、脚、面部表情；目的是让多个动画师画出来像同一个人，偏离标准叫“off-model”（[Model sheet](https://en.wikipedia.org/wiki/Model_sheet)）。
- **Color script（色彩脚本）**：按场次/段落确定色调和光线，让整片的色彩和情绪有弧线；据报道，Pixar 会为每部电影做 color script，用来定义每个场景的色板和光线（[SlashFilm](https://www.slashfilm.com/779272/the-morning-watch-pixars-finding-nemo-color-script-dave-grohl-gets-saucy-on-hot-ones-more/)）。
- **Expression sheet、prop sheet、environment design、style guide**：把表情、道具、场景、材质、渲染风格也变成可引用资产。

这套东西的本质是：**把“外观”从每个镜头里抽出来，变成一份可复用、可版本化的参考。** 这正是 AI 生成最需要的“角色一致性”基础。

### 3.3 Story reel：把分镜剪成电影

DreamWorks 的故事艺术家对流程的描述很直接：“我的工作是把剧本翻译成一个视觉 story reel。我向导演和 head of story 提案，他们和剪辑部门一起确保一切符合导演的创作意图。”（[Foundry](https://colorway.foundry.com/ja/insights/film-tv/how-to-train-your-dragon-flix)）Flix 在这里承担的是分镜的版本、重编号、评审拼装和跨部门同步。

Pixar 的剪辑部门则被描述为“轮子的轴心”：从最早的 story reel 阶段就参与，把故事、编辑、各部门连起来；story reel 相当于在剪辑室里先做出“第一版电影”，可以反复看、反复改（[Cartoon Brew](https://www.cartoonbrew.com/books/making-the-cut-pixar-kinder-osteen-218914.html)）。

Story reel / animatic 的通用定义是：把分镜静帧按顺序剪在一起，配上临时对白（scratch vocals）、音乐和音效，用来检查表演、镜头位置、镜头表和节奏；发现问题就改分镜和音轨，再做一版，直到分镜锁定（[Storyboard: Animatics](https://en.wikipedia.org/wiki/Storyboard#Animatics)）。它的价值在于：**在进入动画/生成之前，把“这条片子成不成立”试出来。**

一句值得记住的话：**分镜是一组关于时间的声明，animatic 是验证这些声明的地方。** 看一遍就会发现“第 112 个 cut 长了两秒”“为了省时间剪掉的反应镜头其实是这场戏需要的”（[ScreenWeaver](https://www.screenweaver.ai/blog/anime-storyboard-e-konte)）。

### 3.4 为什么不是“画完再改”

动画电影的制作偏线性：前期分镜和概念设计像建筑图纸，后面的模型、动画、场景、特效、灯光合成都是按图施工；如果前期反复修改，后续每一个环节都要改，成本很高（[网易/新京报](https://m.163.com/dy/article/JPPTLBB40512D3VJ.html)）。所以工业管线把“改”集中到最便宜的地方：beat board、storyboard、story reel。到了 animation 和 lighting，改动就是真金白银。

### 3.5 对本项目的启示

- 时间线不仅可以放最终素材，也可以先放“计划中的镜头”：简图 + 目标时长 + 临时音频，就是 animatic。
- 生成之前应该有一道“animatic gate”：整片节奏、镜头覆盖、时长、转场都成立，再开始批量生成。
- 生成后的片段应该替换时间线上的计划镜头，而不是另起一条时间线；这样“计划”和“成片”始终对得上。

---

## 4. 日本动画：e-conte 是施工图

### 4.1 阶段

日本动画的公开流程可以概括为：

- **前期**：脚本、系列构成、角色设计、美术设定、绘コンテ（e-conte）；有的作品会先做 image board 来统一视觉想象。
- **中期**：layout（构图/空间）、原画（key animation）、动画/中割（in-between）、上色（finishing）、摄影合成（compositing）。
- **后期**：编辑（cutting）、配音/演技、完成。

Studio Eight Bit 的现场报道把这条链讲得很清楚：前期根据脚本做角色设计、美术设定和 image board，再做成 storyboard；storyboard 是“用怎样的机位去拍脚本内容、如何把 cut 叠成连续影像”的蓝图，由画面和文字指示组成。中期按 storyboard 做 layout、原画、timesheet、中割、上色、摄影合成；后期剪辑和配音（[ABEMA Times](https://times.abema.tv/en/articles/-/10229971)）。研究界也把 e-conte 称为日本动画的“蓝图”（[Griffith, CHI 2024](https://dl.acm.org/doi/10.1145/3613904.3642121)）。

### 4.2 e-conte 的九个栏目

| 栏目 | 内容 | 对 AI 镜头规格的映射 |
|---|---|---|
| Scene / cut | 场号、cut 号；一场包含多个 cut | `scene_id`、`shot_id` |
| Page number | 这一页在整集中的位置 | `sequence`、`order` |
| Action | 表演、调度、摄影机运动 | `action`、`staging`、`camera` |
| Storyboard area | 构图和粗略表演的缩略图 | `board.image`、`composition` |
| Frame | 与最终画幅一致的 16:9 框 | `aspect_ratio`、`framing` |
| Bleed area | 框外空间，供摇镜/俯仰/overshoot 使用 | `reframe`、`safe_area`、`camera_margin` |
| Dialogue and SFX | 台词、拟声/音效 | `audio.dialogue`、`audio.sfx` |
| Time | 该 cut 的长度，秒+帧 | `duration_frames` |
| Total time | 整页累计时长 | `sequence_duration` |

这张表来自对 e-conte 栏目结构的整理（[ScreenWeaver](https://www.screenweaver.ai/blog/anime-storyboard-e-konte)），它引用的是 Sakuga Wiki 的条目；栏目名在不同工作室会有差异，但“cut 号、画面、动作、台词/音效、时间”这几项是稳定的。五栏核心（cut、画面、动作、台词、时间）在另一份实践指南里也有相同描述（[Slopcannon](https://slop.cc/wiki/e-konte)）。

传统 2D 动画还有一层 exposure sheet（dope sheet / X-sheet）：逐帧记录动作提示、对白、动画层、背景和摄影机指令，一秒 24 格，每 8 格加粗；e-conte 决定一个 cut 的意图和总时长，exposure sheet 决定这个时长里每一帧怎么排（[Exposure sheet](https://en.wikipedia.org/wiki/Exposure_sheet)）。数字管线通常不需要 X-sheet，但“帧级时间”这个概念保留在 `duration_frames` 和 animatic 里。

### 4.3 三条硬规则

**第一，cut 是组织单位。** 日本动画把 cut 当作一个不间断的镜头，也是从 layout 到最终合成的组织键：cut 87 是一个文件夹、一张 timesheet、一条付款记录、一个 deadline；它最初只是分镜页左边的一个数字（[ScreenWeaver](https://www.screenweaver.ai/blog/anime-storyboard-e-konte)）。

**第二，时间是承诺。** 时间栏用“秒+帧”写，24fps 下 1.5 秒写作 `(1+12)`；动画预算可以细到帧，动画师可以调整动作内部的节奏，但不能改总时长；如果制作办公室预填的 timesheet 和 konte 不一致，以 timesheet 为准（同上）。

**第三，cut 边界不能从画面推断。** 同一页上，下面的画更晚发生，但“新的一张画”不等于“新的 cut”：一个 cut 可能需要十几张缩略图来表现运动，一个城市建立镜头可能只需要一张。只有 cut 栏有权决定一个镜头在哪里结束；bleed 区不是装饰，而是摇镜/俯仰/overshoot 的指令（同上）。

### 4.4 AI 的边界：画帧可以，定 cut 不行

同一份行业实践指南给出的分工很明确：生成工具擅长“把已经设计好的 cut 画成可读的帧”，擅长在喂参考图的情况下保持角色外观，擅长给提案/委员会看；不擅长决定 cut 边界、分配时长、处理需要 bleed 区的摄影机运动。它的建议是：**生成画面，数字自己写。**（[ScreenWeaver](https://www.screenweaver.ai/blog/anime-storyboard-e-konte)）

这和 e-conte 是“蓝图”的定位一致：e-conte 在 layout 和原画的上游，含糊的板子会产生含糊的 layout，再下游就是昂贵的修正；layout、原画、中割、修型这些部门不跟剧本对话，他们跟板子对话（同上）。所以板子上的字段不是“参考信息”，而是“施工依据”。

### 4.5 对本项目的启示

- 镜头表必须有稳定的 cut 号，且和文件夹、任务、版本、生成记录用同一个 ID。
- 时长用帧而不是秒，至少内部用帧；秒只做显示。这样和 fps、时间线、模型支持的时长对齐。
- 画面字段要能表达“从哪看、看什么、主体在哪、画外有什么”；bleed/reframe 可以映射成“允许多少后期重构/裁切”的字段。
- cut 边界和时长由人决定；AI 可以给候选，但不能默认接受模型的自然时长。

---

## 5. 中国动画电影：分镜是跨公司协作的“图纸”

### 5.1 《哪吒 2》：分镜师一天画两个镜头

《哪吒 2》的公开报道给出了几个很有说服力的数字：144 分钟、5 年半、138 家中国动画公司、4000 多名动画人；一位联合分镜师正常一天画 10–20 个镜头，但在《哪吒 2》的大场面里常常一天只能画 2 个镜头，不到一秒钟；陈塘关大战里章鱼怪和李靖的打戏，剧本只有“厮杀在一起”五个字，分镜师画了整整半年（[网易/新京报](https://m.163.com/dy/article/JPPTLBB40512D3VJ.html)）。

更关键的是行业人士的总结：整个动画电影制作偏线性，像建筑需要设计图，前期分镜设计就是图纸，后面的制作环节是把图纸落地；如果前面反复修改，后续每一个环节都要改，成本很高（同上）。这正是“上游不定、下游返工”的工业版注脚。

报道还提到，前期分镜和概念设计结束后，交付给模型组、动画组、场景组、特效组、灯光合成及配音组等中期部门同步工作；后期进入渲染、合成、剪辑（同上）。这意味着，138 家公司协同的前提不是“大家看同一份剧本”，而是“大家看同一套镜头编号、资产和版本”。

### 5.2 《流浪地球》：160 分钟动态故事板

《流浪地球》的案例说明真人电影也会把“动态分镜”做到接近成片长度：重场戏用 PreViz，其余文戏和过场戏用动态故事板，剪满 160 分钟；粗剪阶段 4000 多个视效镜头，最终留下约 2200 个；后期管理强调镜头优先级、视效分包、进度跟踪、素材出入流程和水印标准（[中国电影报](https://chinafilmnews.cn/Html/2019-02-28/799.html)）。

这说明“动态分镜”不是动画专属，而是所有高成本、强视效项目的通用做法：先用便宜的方式把整片看一遍，再决定钱花在哪。

### 5.3 对本项目的启示

- 跨公司/跨团队协作时，分镜表是合同附件：镜头号、时长、资产、版本、状态必须能对上。
- 变更要能回答“改了哪个镜头、影响哪些下游、当前用哪一版”，不能靠聊天记录。
- 分镜越接近“施工图”，下游返工越少；但分镜的精度要和项目体量匹配，短剧不需要电影级精修。

---

## 6. AI 原生管线：提示词不是“写”出来的，是“编译”出来的

### 6.1 模型侧：提示词的结构已经收敛

主流视频模型的厂商/平台文档，结构高度相似：

| 模型/工具 | 文档推荐结构 | 参考资产机制 | 明确边界 |
|---|---|---|---|
| Sora 2 | 镜头取景、景深、动作分 beat、光线和色板、主体锚点 | Characters API 上传角色，最多两个角色引用；分辨率/时长/角色是 API 参数，不写在散文里 | 短片段更遵守指令；同一 prompt 多次生成结果不同；多镜头可以写在一个 prompt 里，但每个镜头块要独立 |
| Veo 3.1 | Cinematography + Subject + Action + Context + Style & Ambiance | 首帧/尾帧；Ingredients to Video 最多三张参考图（角色、背景、纹理） | 对白/SFX/环境声要显式写；模型名、时长、画幅不要写进 prompt 文本 |
| Runway AI previs | 脚本 → shot list（取景、运动、情绪目的）→ 参考帧 → 锁定 References → 动态片段/animatic | References 锁定角色、地点、风格 | 生成帧没有可测量空间；精确空间连续性不保留；摄影机运动可能物理上不可行 |

来源：Sora 2 提示词指南（[OpenAI Cookbook](https://developers.openai.com/cookbook/examples/sora/sora2_prompting_guide)）；Veo 3.1 指南（[Google Cloud](https://cloud.google.com/blog/products/ai-machine-learning/ultimate-prompting-guide-for-veo-3-1)）；Veo Ingredients 更新（[The Verge](https://www.theverge.com/news/861257/google-veo-3-1-ai-video-ingredients-vertical-update)）；Runway AI previs（[Runway](https://runway.com/resources/ai-previs)）。

这些指南的共同点是：**提示词要写“镜头语言”，不要写“文学描述”。** 主体、动作、环境、光线、风格、声音，各自有位置；参考图负责外观，散文负责这一次的动作和镜头。这个结构和分镜表/镜头表是天然对应的。

### 6.2 实践侧：一条 beat 一条 prompt

一个被公开的 AI 电影管线把流程写成 11 步：剧本分解 → 角色资产（7 面转面图）→ 场景资产 → 道具资产 → 声音资产 → 镜头规划（2–3 秒一个 beat）→ 提示词写作（一条 beat 一条 prompt，区分 immutable/mutable）→ 生成 → 首尾帧链接 → 音频后期 → 剪辑（[AI Cinematic Pipeline](https://github.com/billpar/ai-cinematic-pipeline)）。

它的几条经验值得直接借用：

- **7 面转面图**：正面、左右侧、背面四个全身，加三个头部角度；中性灰底、统一光线、服装/发型/肤色/比例不变；锁定后不要中途重生成（[角色资产文档](https://github.com/billpar/ai-cinematic-pipeline/blob/main/docs/02-character-asset-creation.md)）。
- **immutable vs mutable**：角色/场景/光线风格/整体影调在一个场景内不变；机位、动作、表情、声音每条 beat 变；同一个场景里，immutable 元素不能换一种说法（[一致性技术](https://github.com/billpar/ai-cinematic-pipeline/blob/main/docs/04-consistency-techniques.md)）。
- **首尾帧链接**：把上一条的最后一帧作为下一条的首帧，是保持角色位置、光线、空间关系最有效的技巧；seed 复用和角色参考图是辅助（同上）。
- **镜头表 CSV**：列包括 scene、beat、timestamp、shot_type、lens、characters_in_frame、setting、immutable_lighting、action、expression_physical、dialogue、voiceover、audio_notes、elements_attached、seed、start_frame_source、status（[模板](https://github.com/billpar/ai-cinematic-pipeline/blob/main/templates/shot-list-template.csv)）。

中国的 AI 短剧实践也给出了一条真实的生产线：剧本（往往不是 AI 写的）→ 导演/监制拆人设、人物关系、场景、冲突点 → 大模型提取世界观/人物/场景/道具 → 人工和平台确认设定 → 生成角色图 → 分镜 → 样片 → 批量“抽卡” → 后期精修。一个 60 集、100 多分钟的 AI 短剧，按 15 秒一条算大约 400 条；一条 15 秒的片子要抽 10–15 条，顺利的话 4–5 条可用；前期从剧本到分镜，传统可能需要一周以上，用 AI 压缩到一两天（[中国之声/搜狐](https://m.sohu.com/a/1016209326_362042/)）。

这篇报道还点出了一个非常具体的一致性 bug：分段制作时，这一集结尾人物站在场景左边，下一集的人可能站在右边，需要在衔接处提前把位置定好（同上）。这不是 prompt 能解决的，是 **shot state / continuity** 的问题。

另一个中文 AI 分镜规范把这点工程化了：13 列分镜表（镜号、画面、时长、镜头、景别、内容、台词、镜头运动、画面描述、人物站位俯视图、音效、衔接、备注），加上 `@角色/场景/道具` 引用协议，以及“结构化 shots JSON → 服务端确定性渲染分镜表”的做法；分镜表是视图，shots JSON 才是事实源（[tapcanvas](https://github.com/anymouschina/tapcanvas/blob/main/apps/agents-cli/skills/tapcanvas-storyboard-expert/references/storyboard-production-reference.md)）。还有一个中文项目把流程拆成 Beat Board（九宫格）→ Sequence Board（四宫格）→ Motion Prompt，并在每阶段加导演/编剧审核（[novel-to-script-team](https://github.com/Supreme-Ultimate/novel-to-script-team)）。

这些项目不是工业级，但它们的结构说明了一件事：**AI 原生管线真正缺的不是“更强的模型”，而是“镜头级的结构化状态”。**

### 6.3 一个可编译的镜头规格

把上面的字段收拢，一个镜头可以长这样（JSON 只是示例，不是已采纳的契约）：

```json
{
  "schema_version": 1,
  "kind": "storyboard-shot",
  "id": "SH003",
  "scene_id": "S001",
  "beat_id": "B002",
  "source": {"scene": "S001", "sentence_start": 4, "sentence_end": 5},
  "duration_frames": 72,
  "board": {"image": "boards/SH003.png", "status": "approved"},
  "framing": {
    "size": "medium-close",
    "angle": "eye-level",
    "lens_mm": 50,
    "composition": "OTS over A's left shoulder",
    "headroom": "tight"
  },
  "camera": {
    "movement": "slow push-in",
    "start_event": "on A's last word",
    "end_event": "before B turns"
  },
  "staging": {
    "subjects": [
      {"asset_id": "CH_A", "position": "frame-left", "facing": "right", "action": "hands still"},
      {"asset_id": "CH_B", "position": "frame-right", "facing": "left", "action": "turns head"}
    ],
    "axis": "A-B",
    "screen_direction": "A-to-B",
    "eyeline_match": true
  },
  "lighting": {
    "time": "night",
    "key": "warm practical screen-left",
    "palette": "amber/teal",
    "contrast": "high"
  },
  "audio": {
    "dialogue": [{"character": "CH_A", "line": "..."}],
    "sfx": ["..."],
    "ambience": "..."
  },
  "refs": ["CH_A", "CH_B", "LOC_01"],
  "continuity": {"from": "SH002", "to": "SH004", "locks": ["wardrobe", "lighting", "axis"]},
  "generation": {"template": "veo-3.1", "seed": 12345}
}
```

编译出来的提示词大致是：

```text
[Shot] Medium close-up, 50mm, eye-level, OTS over A's left shoulder.
[Camera] Slow push-in starting on A's last word, ending before B turns.
[Subject] @CH_A: <locked character anchor text>. Hands still.
[Subject] @CH_B: <locked character anchor text>. Turns head.
[Lighting] Night, warm practical from screen-left, amber/teal, high contrast.
[Action] ...
[Audio] ...
```

这里的分工是：

- `<locked character anchor text>` 来自 `bible.json`，是逐字复用的，不在每个镜头里重写。
- `[Shot]`、`[Camera]`、`[Action]`、`[Audio]` 来自 `storyboard.json` 的镜头字段。
- `@CH_A` 这类引用由提示词编译器解析成真实的参考资产；引用不到就 fail，而不是让模型猜。
- `generation` 里的 seed、模型、分辨率等是生成参数，不写进提示词散文；镜头时长仍由 `duration_frames` 管。这和 Sora 的 API 参数、Veo 的“不要把模型名/时长/画幅写进 prompt”一致。

**结论：提示词是 `bible + storyboard + model template` 的编译产物，不是手写的自由文本。** 这也是“避免返工”的核心：改设定改一处，改镜头改一行，重新编译，而不是在几十条 prompt 里手动找替换。

### 6.4 生成前的门

工业管线靠门控制返工；AI 管线也应该有确定性门，而不是“生成出来再看”。

| 门 | 检查 | fail 的后果 |
|---|---|---|
| 覆盖 | 每场/每 beat 都有镜头；每句台词都落在某个镜头；没有 orphan shot | 补镜头/合并，不进入生成 |
| 时长 | 每镜 > 0；总时长对齐目标；帧数按 fps 取整；和 animatic 一致 | 重排/重切，不进入生成 |
| 连续性 | 轴线、视线、出入画方向、服装、光线、道具位置；相邻镜头的 from/to 状态一致 | 补中性镜/重画/重排 |
| 参考资产 | 每个出镜角色/场景/道具都有锁定资产；`@ref` 全部解析；没有未登记资产 | 补资产或改镜头，不生成 |
| 提示词 | 必填字段齐全；immutable 字段没有互相冲突；模型参数合法 | 编译失败，不生成 |
| 分镜 | 画幅、构图、主体可读；board 状态 approved；必要时有站位图 | 重画/补图 |

这些门里，覆盖、时长、引用、字段完整性都可以由代码确定性检查；连续性的一部分可以规则化（轴线、视线、方向），一部分需要人或 VLM 评审。**先跑确定性检查，再跑模型评审**，和本仓库“确定性内核优先”的路线一致。

### 6.5 生成后的门

生成之后至少要看：

- **身份**：角色是否还是同一个人（脸、发型、服装、体型）。
- **构图**：景别、角度、主体位置是否和 board 一致。
- **动作/运动**：动作是否完成；摄影机运动是否和设计一致；有没有物理上不可能的运动。
- **时长**：生成片段是否覆盖目标时长；不够就补/裁/变速，不要默认接受。
- **声音**：对白、SFX、环境声是否匹配；口型/语气是否需要后期。
- **连续性**：接上一镜的最后一帧/下一镜的第一帧是否成立。
- **Provenance**：模型、prompt、seed、参考资产、生成时间、上游版本；没有这些，无法复现和追责。

Digital Production 报道的 ComfyUI–ShotGrid 集成就是一个工业化的参考：每个 Version 记录 AI 生成器、模型、正/负提示词、seed、采样器/调度器、步数、CFG、上游 Version 血缘；媒体作为 PublishedFile 挂在 Version 下（[Digital Production](https://digitalproduction.com/2026/11/12/comfyui-meets-shotgrid-now-keep-the-receipts/)）。这套东西不一定要一次做完，但字段设计应该留好。

### 6.6 局限：prompt 不是合同

需要明确几条边界：

- **生成帧没有可测量的 3D 空间。** 它可以告诉你“这个构图看起来行不行”，不能告诉你“轨道要多长、摇臂要多高、演员和桌子的距离是多少”（[Runway](https://runway.com/resources/ai-previs)）。
- **精确的空间连续性不会自动保持。** References 能保住角色/地点/风格，保不住“上一镜在左、下一镜在右”的空间关系；需要显式的 shot state 和首尾帧。
- **摄影机运动可能物理上不可行。** 生成模型可以提出看起来很棒但拍不出来的运动；在真人项目里这是废镜头，在纯生成项目里也要确认它和前后镜头接得上（同上）。
- **prompt 不是合同。** 同一个 prompt 多次生成结果不同；模型会“创作”，不会“执行”。所以需要 best-of-N、评审、版本和人工 gate，而不是指望一条 prompt 百分百复现。
- **模型会变。** 厂商升级/下线模型后，旧 prompt 的行为会变；provenance 和参考资产比 prompt 文本更耐久。

### 6.7 对本项目的启示

- 不要做“一句话→一条视频”的生成器；要做“设定集→镜头表→编译 prompt→批量生成→评审→时间线”的管线。
- prompt 不要作为事实源；事实源是 `bible.json` + `storyboard.json`，prompt 是编译结果。
- 参考资产、seed、模型参数、上游版本要落盘；否则无法复现和比较。
- 生成前的确定性门比生成后的 VLM 评审更便宜，应该先做。

---

## 7. 制作管理系统：工业级的“事实源”

### 7.1 共同数据模型

ShotGrid、ftrack、Kitsu 这类制作管理系统，虽然界面和术语不同，但核心模型高度一致：

| 实体 | 作用 | 在 AI 管线里的对应 |
|---|---|---|
| Project / Production | 项目 | `project.json` |
| Episode / Sequence | 集/序列 | `episode_id`、`sequence_id` |
| Shot | 镜头，制作和排期的最小单位 | `shot_id` |
| Asset | 角色、场景、道具、概念图 | `asset_id` + 参考图 |
| Task | 某镜头/资产的某道工序 | `task`（分镜/生成/评审/合成） |
| Version / PublishedFile | 某次提交的可审版本和文件 | `generation_version` + 视频/图 |
| Note / Review | 评审意见和状态 | `review_status`、`notes` |
| Edit / Cut | 剪辑版本，提供镜头时长和顺序 | `timeline` / `edit` |

Kitsu 的文档把这条链讲得很具体：Breakdown & Casting 把资产 cast 到镜头；分镜/animatic 完成后，把每个镜头的帧数和 in/out 填回镜头表；Edit 是一个可跟踪的实体，代表整片、预告或不同剪辑版本；Publish 是把某个任务的成果作为可审版本提交（[Kitsu breakdown](https://kitsu.cg-wire.com/guides/production/breakdown-casting/)、[Kitsu shots](https://kitsu.cg-wire.com/guides/production-structure/manage-shots/)、[Kitsu edits](https://kitsu.cg-wire.com/guides/review-publishing/manage-edits/)、[Kitsu publish](https://kitsu.cg-wire.com/guides/review-publishing/publish/)）。

ShotGrid 的 API 示例则展示了 Version 怎么挂到 Shot 和 Task 上：Version 有 status、entity（Shot）、sg_task、user，上传的 movie 会转码并生成缩略图/胶片条（[ShotGrid 开发者文档](https://developers.shotgridsoftware.com/python-api/cookbook/examples/basic_create_version_link_shot.html)）。ftrack 也是类似的项目/对象/任务/版本/评审模型（[ftrack 文档](https://docs.ftrack.com/)）。

### 7.2 关键机制

- **Asset casting**：镜头不重复描述角色，而是引用资产；换服装/换场景只改资产版本，所有引用它的镜头跟着变。
- **Frame range 回填**：animatic 定剪后，镜头的帧数/in/out 回填到镜头表；镜头表不是“估计”，而是和剪辑一致的事实（Kitsu 的 Manage Shots 明确说“Once your animatic is done...”）。
- **Version 绑定 Shot/Task**：每个生成结果都是一个 Version，挂到具体镜头和任务；评审、比较、回滚都基于 Version，而不是文件名。
- **Edit/Cut 作为时间源**：剪辑版本决定镜头顺序和时长；镜头表、资产、生成都要和当前 cut 对齐。
- **Provenance**：AI 生成额外记录模型、prompt、seed、参考资产、上游 Version；这是传统管线没有、AI 管线必须补的一层。
- **Review status**：approved / changes requested / pending 这类状态要能驱动下游；没有状态，下游不知道能不能用。

### 7.3 交换格式

工业管线不要求所有人用同一个软件，但要求能交换：

- **Fountain**：纯文本剧本，可版本控制、可解析（[Fountain](https://fountain.io/syntax/)）。
- **CSV**：镜头表、资产表、抽卡记录的最低共同标准；Kitsu 也支持 CSV 导入/更新镜头。
- **OpenTimelineIO（OTIO）**：时间线的通用 JSON 结构，带 Clip、Track、MediaReference、TimeRange；适配器覆盖 AAF、CMX3600 EDL、FCP XML 等（[OTIO 结构](https://opentimelineio.readthedocs.io/en/latest/tutorials/otio-timeline-structure.html)、[OTIO 适配器](https://opentimelineio.readthedocs.io/en/latest/tutorials/adapters.html)）。
- **EDL / AAF / FCP XML**：剪辑和后期交接的常用格式；EDL 是 cut list，AAF/XML 携带更完整的时间线信息。
- **USD**：3D 场景/资产/组合的通用描述，适合有 3D 预览/虚拟制片需求的项目（[OpenUSD](https://openusd.org/release/intro.html)）。

对本项目来说，JSON 是内部事实源，Fountain/CSV/OTIO 是导入导出视图；不要为了兼容所有格式一次做完，先把内部 schema 和 ID 稳定下来。

### 7.4 对本项目的启示

- 工业级的核心不是“有一个数据库”，而是“每个工件都有 ID、版本、状态、引用关系”。
- 镜头表要能回填 animatic 的真实帧数；生成片段要挂到镜头和版本上，而不是散落在文件夹里。
- prompt 的 provenance 要单独设计；它是 AI 管线相对传统管线新增的一层，不是可选装饰。
- 交换格式按需做：先把 `storyboard.json` 和 `prompt_sheet.json` 的 schema 定稳，再考虑 Fountain/OTIO 导出。

---

## 8. 推荐给本仓库的最小管线

> 这一节是调研结论，不是已采纳的架构决定；具体 schema 和命令应在后续 ADR/PR 里定。

### 8.1 工件链

```text
bible.json                 # 设定集：角色/场景/道具/风格/色板，锁定锚文本和参考图
  → screenplay.json        # 剧本：场次/beat/动作/对白/来源锚点（screenplay-adapter 输出）
  → storyboard.json        # 分镜：scene → shot，含简图、时长、景别、机位、调度、声音、连续性
  → animatic               # 把 board 按目标时长放进 project.json 的时间线，配临时音频
  → prompt_sheet.json      # 编译后的提示词：每镜的 prompt、refs、模型参数、seed、状态
  → generation jobs        # 生成/抽卡 → assets/ + versions/
  → project.json           # 时间线引用 shot_id / asset_id / version，渲染成片
```

这里要区分两层事实源和一个派生层：

- **编辑事实源**：`project.json` 的时间线。它决定成片里到底用哪一段、什么顺序、多长。
- **规划事实源**：`bible.json` + `storyboard.json`。它决定每个镜头应该长什么样、为什么这么切。
- **派生视图**：`prompt_sheet.json`、分镜表 Markdown/CSV、Fountain、渲染报告。它们都可以从上面两层重建，不是第二份事实。

### 8.2 文件职责

所有 JSON 工件都应带 `schema_version`；新增工件沿用 `adaptation.json` 的 `kind` 约定；破坏性变更加版本号和 migration（`project.json` 当前只有 `schema_version`，是否补 `kind` 由契约版本决定）。

| 文件 | 事实源 | 关键字段 | 主要门 | 派生视图 |
|---|---|---|---|---|
| `bible.json` | 设定集 | 角色/场景/道具 ID、锁定锚文本、参考图、色板、风格、版本 | 资产完整性、引用可解析、锚文本非空 | 角色卡、场景卡、资产清单 |
| `screenplay.json` | 剧本 | 场次/beat、动作、对白、来源锚点、时长估算 | 覆盖、人物、格式、时长 | Fountain/Markdown |
| `storyboard.json` | 分镜 | `shot_id`、`scene_id`、`beat_id`、`duration_frames`、`framing`、`camera`、`staging`、`lighting`、`audio`、`board`、`refs`、`continuity` | 覆盖、时长、连续性、引用、字段完整 | 分镜表 CSV/Markdown、站位图、animatic |
| `prompt_sheet.json` | 编译结果 | `shot_id`、`template`、`prompt`、`refs`、`model`、`seed`、`negative`、`status`、`provenance` | 字段完整、refs 可解析、immutable 不冲突 | 可读 prompt 列表、生成任务 |
| `project.json` | 编辑/时间线 | `timeline.clips[]`、`asset_id`、`start`、`source_in/out`；`shot_id`/`version` 是建议扩展，当前 M0 只有 `asset_id` | 时间线连续、素材存在、引用有效 | 预览、渲染、渲染报告 |

### 8.3 实施顺序

1. **先定 schema 和 ID**：`shot_id` 和 `scene_id` 稳定；`storyboard.json` 能表达一个镜头的全部必填字段；`bible.json` 能表达资产和锁定锚文本。
2. **再做 storyboard/animatic 门**：把 board 放进时间线，按目标时长播放；检查覆盖率、总时长、镜头边界、连续性规则（轴线、视线、方向）。
3. **再做 prompt 编译器**：每个模型一个模板；immutable 从 `bible.json` 注入，mutable 从 `storyboard.json` 注入；编译失败要可定位（哪个镜头、缺哪个字段、哪个 ref 解析不到）。
4. **再做生成适配器**：provider 无关的生成任务；记录 model、prompt、seed、refs、上游版本；best-of-N 和人工选择；生成结果挂到 `shot_id` 和 Version。
5. **最后做 QC 和 UI**：确定性 QC（ffprobe、抽帧、时长、音频）先于 VLM 评审；UI 只做审阅和选择，不替代工件。

### 8.4 不做什么

- **不让 LLM 决定 cut 边界和时长。** 它可以帮助拆 beat、提候选，但 cut 是导演决策；e-conte 的行业实践已经说明，边界和时长是承诺，不是生成参数。
- **不把 prompt 当事实源。** prompt 是编译结果；改设定/改镜头后应该重新编译，而不是手动改几十条 prompt。
- **不要求所有项目都全量工件。** 微短剧可以只有 bible + shot table + prompt；电影级项目才需要 color script、精修 board、techvis。工件深度随项目体量调整。
- **不承诺 AI previs 能替代 techvis。** 生成帧没有可测量空间；涉及真实布景、道具、演员走位时，仍然需要 3D/技术预览。
- **不把最终 MP4 当项目状态。** 它只是某个 revision 的渲染产物；时间线和工件才是可编辑、可恢复的状态。

---

## 9. 参考资料

### 行业管线与工件

- Storyboard（含 animatics）：<https://en.wikipedia.org/wiki/Storyboard>
- Model sheet：<https://en.wikipedia.org/wiki/Model_sheet>
- Exposure sheet：<https://en.wikipedia.org/wiki/Exposure_sheet>
- Previsualization：<https://en.wikipedia.org/wiki/Previsualization>
- Script breakdown：<https://en.wikipedia.org/wiki/Script_breakdown>
- Production board：<https://en.wikipedia.org/wiki/Production_board>
- StudioBinder, Shot List Template：<https://www.studiobinder.com/blog/shot-list-template-free-download/>
- SACD, Definitions and Remuneration of Animation Bibles：<https://www.sacd.fr/sites/default/files/bulletin_declaration_crea_serie_def_bible_en.pdf>
- ScreenWeaver, Anime Storyboard: How E-Konte Works：<https://www.screenweaver.ai/blog/anime-storyboard-e-konte>
- Slopcannon, E-konte: the anime storyboard：<https://slop.cc/wiki/e-konte>
- ABEMA Times, Studio Eight Bit anime production process：<https://times.abema.tv/en/articles/-/10229971>
- Jun Kato, Griffith: A Web-based Tool for Authoring Anime Storyboards (CHI 2024)：<https://dl.acm.org/doi/10.1145/3613904.3642121>
- Cartoon Brew, Making the Cut: Pixar editorial：<https://www.cartoonbrew.com/books/making-the-cut-pixar-kinder-osteen-218914.html>
- Foundry, How DreamWorks created the visual story reel using Flix：<https://colorway.foundry.com/ja/insights/film-tv/how-to-train-your-dragon-flix>
- SlashFilm, Pixar's Finding Nemo color script：<https://www.slashfilm.com/779272/the-morning-watch-pixars-finding-nemo-color-script-dave-grohl-gets-saucy-on-hot-ones-more/>
- 中国电影报，《从〈流浪地球电影制作手记〉看中国电影工业体系搭建》：<https://chinafilmnews.cn/Html/2019-02-28/799.html>
- 网易/新京报，《144分钟〈哪吒2〉背后，4000多名动画人的5年半》：<https://m.163.com/dy/article/JPPTLBB40512D3VJ.html>
- 中国之声/搜狐，《从0到1全流程解码：一部纯AI短剧是如何炼成的？》：<https://m.sohu.com/a/1016209326_362042/>
- Runway, What is AI previs?：<https://runway.com/resources/ai-previs>

### 数据模型、标准与交换格式

- ShotGrid Developer, Create a Version linked to a Shot：<https://developers.shotgridsoftware.com/python-api/cookbook/examples/basic_create_version_link_shot.html>
- ftrack Documentation：<https://docs.ftrack.com/>
- Kitsu, Breakdown & Casting：<https://kitsu.cg-wire.com/guides/production/breakdown-casting/>
- Kitsu, Manage Shots：<https://kitsu.cg-wire.com/guides/production-structure/manage-shots/>
- Kitsu, Managing Edits：<https://kitsu.cg-wire.com/guides/review-publishing/manage-edits/>
- Kitsu, Publishing：<https://kitsu.cg-wire.com/guides/review-publishing/publish/>
- OpenTimelineIO, Timeline Structure：<https://opentimelineio.readthedocs.io/en/latest/tutorials/otio-timeline-structure.html>
- OpenTimelineIO, Adapters：<https://opentimelineio.readthedocs.io/en/latest/tutorials/adapters.html>
- Fountain Syntax：<https://fountain.io/syntax/>
- OpenUSD Introduction：<https://openusd.org/release/intro.html>
- Digital Production, ComfyUI Meets ShotGrid: Now Keep the Receipts：<https://digitalproduction.com/2026/11/12/comfyui-meets-shotgrid-now-keep-the-receipts/>

### AI 提示词与实践

- OpenAI Cookbook, Sora 2 Prompting Guide：<https://developers.openai.com/cookbook/examples/sora/sora2_prompting_guide>
- Google Cloud, The ultimate prompting guide for Veo 3.1：<https://cloud.google.com/blog/products/ai-machine-learning/ultimate-prompting-guide-for-veo-3-1>
- The Verge, Google's Veo Ingredients to Video update：<https://www.theverge.com/news/861257/google-veo-3-1-ai-video-ingredients-vertical-update>
- AI Cinematic Pipeline：<https://github.com/billpar/ai-cinematic-pipeline>
- tapcanvas, 分镜表格输出格式与 @引用协议：<https://github.com/anymouschina/tapcanvas/blob/main/apps/agents-cli/skills/tapcanvas-storyboard-expert/references/storyboard-production-reference.md>
- novel-to-script-team：<https://github.com/Supreme-Ultimate/novel-to-script-team>

---

*调研方法：2026-11-25 至 2026-11-26 阅读公开行业访谈、厂商文档、标准文档和开源项目；对“story reel / e-conte / 分镜是图纸 / AI previs 边界 / 抽卡成本”等关键事实做了多来源交叉；未实际运行视频模型，AI 短剧的成本和时长为报道方自报；未接触任何工作室内部资料。*
