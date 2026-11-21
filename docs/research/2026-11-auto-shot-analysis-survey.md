# 自动拉片 Video Agent 调研（2026-11）

**调研问题**：想做一个自动拉片的 video agent，最基础的能力是“切分镜头，再逐镜头分析视听语言”。目前有哪些相关论文、数据集、开源工具和产品实践？应该怎么把它们拼成一个可用的系统？

**范围**：以电影/剧集/短片的“视听拉片”为主，覆盖镜头切分、逐镜属性、场景聚合、报告生成和 agent 工程；不展开视频生成和纯剧情解说。

**数据快照**：2026-11-21。GitHub star 只代表社区热度，不代表工程质量；论文指标来自各自 benchmark，不能直接横向比较。

---

## 0. 一页结论

1. **这不是“一个视频模型”能做完的事。** 可靠的做法是把拉片拆成四层：**机器测量 → 模型判断 → 代码验收 → 人审/交付**。镜头边界、时长、帧率、运动量这些事实必须由 CV 测量；VLM（视觉语言模型）只负责“景别、角度、运镜、构图、光线、色彩、叙事功能”这些需要看画面才能下的判断。

2. **镜头切分已经相当成熟，但远没有“解决”。** TransNetV2 在 BBC Planet Earth 上 F1 96.2、RAI 93.9，但在更难的 ClipShots 上只有 77.9；2026 年的 OmniShotCut 在包含渐变、跳切、现代短视频的新基准上 range F1 0.881，而 PySceneDetect/TransNetV2/AutoShot 在同一基准上只有 0.75–0.82。老 benchmark 饱和，真实素材仍有明显差距。

3. **逐镜视听语言才是瓶颈。** CineTechBench 的 7 维静态技术问答，最好的 GPT-4o 也只有 70.16%；运镜问答最好的 Gemini-2.5-Pro 只有 56.69%，开源模型平均再低约 15 个百分点。CinematicVQA 进一步发现：模型更会“描述画面”，不擅长“识别手法”，更不擅长“解释叙事功能”；Chain-of-Thought 并不稳定有效。

4. **学术界已经提供了可复用的积木。** MovieNet/MovieShots/CineScale 提供景别、运动、场景标注；Shot2Story/Movie101 提供镜头级描述与叙事；Shot-by-Shot AD 证明“以镜头为单元 + 电影语法先验 + VLM”可以做出 training-free 的 SOTA。它们缺的是把“逐镜分析 + 证据 + 报告”串起来的工程层。

5. **2026 年下半年出现了真正的“AI 拉片”开源实践。** `reelbench-skills`（1.2k stars）把“机器量、模型判、代码查”做成 15 道质量门；`lapian-notes`（814 stars）把“AI 分析包 + 剧情泳道/结构树/情绪曲线”做成可用产品；`dsh-film-analysis` 是功能最全的 DSH 插件，但它只有 2 stars、发布不到三周，且镜头检测用的是 ffmpeg 阈值而非 ML 切分，需要谨慎验证。

6. **商业 API 只解决“切分 + 标签”。** Google Video Intelligence 只做突变镜头，Azure Video Indexer 做场景/镜头/关键帧（含渐变），AWS Rekognition 做 shot segments，Twelve Labs 支持自定义 segment + 结构化字段。没有一家直接输出“这段为什么用特写、光线在讲什么”。

7. **推荐的系统形态**：确定性 CV 内核（SBD + 关键帧 + 运动/色彩/人脸/音频）→ 镜头卡 JSON → 并行 VLM 标注（枚举 + 证据 + 置信度）→ 场景/段落聚合 → LLM 写报告 → 质量门/人审。**镜头表是唯一事实源，报告只是它的一个视图。**

8. **MVP 先做“可核对的镜头表 + 逐镜分析”，不要先做“一键影评”。** 先解决切点、时长、术语一致性和证据链，再谈风格洞察。一个 90 分钟影片大约 800–1500 个镜头，正好适合“并行 map + 分层 reduce”的 agent 架构，而不是把整片塞进一个长上下文。

---

## 1. 问题拆解：什么叫“自动拉片”

### 1.1 两种“拉片”，不要混在一起

中文语境里的“拉片”至少有两个所指：

- **剧作拉片**：按段落/场/幕拆故事，分析人物、冲突、节拍、情绪曲线。`lapian-notes`、`screen-creative-skills` 更偏这一类。
- **视听拉片**：按镜头拆，分析景别、角度、运镜、构图、光线、色彩、声音、剪辑。`reelbench-skills`、`dsh-film-analysis`、MovieNet/CineScale 属于这一类。

用户要的“切分镜头 + 分析各镜头的视听语言”是后者。但只做后者会得到一张“技术参数表”，缺少“这一镜为什么存在”；所以产品上通常是**视听层做证据，剧作层做解释**：

```
镜头事实（可测量）
  → 镜头语义（景别/运镜/光线/色彩/声音）
    → 镜头关系（转场/正反打/匹配剪辑/节奏）
      → 段落功能（铺垫/转折/兑现/留白）
        → 风格与主题（导演手法/类型/母题）
```

### 1.2 可计算化的六个层级

| 层级 | 要回答的问题 | 相对可靠的做法 | LLM/VLM 的角色 |
|---|---|---|---|
| L1 镜头边界 | 哪里切？ | ffmpeg/PySceneDetect/TransNetV2/OmniShotCut | 不参与，最多做异常复核 |
| L2 镜头属性 | 景别、角度、运镜、构图、光线、色彩、焦距/景深 | 专用 CV 分类器 + 可测量代理指标 | 看图判断，必须给证据 |
| L3 镜头内容 | 谁、在哪、做什么、说什么、什么声音 | 人脸/人物跟踪、ASR、音频事件、OCR | 语义归纳与纠错 |
| L4 镜头关系 | 怎么接、为什么这样接 | 转场检测、运动/视线/构图匹配 | 解释剪辑意图 |
| L5 段落/叙事 | 这场戏干什么、节奏如何 | 场景分割、镜头统计、节拍标注 | 段落综述与功能判断 |
| L6 风格/主题 | 导演/类型/母题 | 跨片统计、风格嵌入 | 比较与论证 |

越往下，越依赖电影知识和主观判断；越往上，越应该由代码保证可核对。**把 L1/L2 的事实交给模型自由发挥，是这类系统最常见的失败点。**

### 1.3 一个合格的交付物长什么样

不是一段“这部电影很好看”的影评，而是：

- **镜头表**：镜号、入点/出点、时长、景别、角度、运镜、构图、光线、色彩、景深、转场、声音、画面描述、叙事功能、置信度、证据帧。
- **逐镜卡**：每个镜头一段 3–8 句的分析，必须引用时间码/关键帧。
- **段落综述**：每场戏的功能、节拍、镜头组合、节奏曲线。
- **风格统计**：平均镜长、切速、景别分布、运镜分布、色彩脚本、对白密度。
- **可交互报告**：播放器联动、镜头高亮、筛选/搜索、导出 CSV/Markdown/HTML。
- **可修改**：人可以改切点、改标签、改文案；改完只重跑受影响的部分。

---

## 2. 镜头切分：论文与工程

### 2.1 任务比想象中难

镜头切分（Shot Boundary Detection, SBD）要处理：

- **硬切**：一帧内换画面，最常见。
- **渐变**：叠化、淡入淡出、划像、甩切、morph；边界往往跨多帧。
- **伪切点**：闪光、爆炸、手电晃动、快速摇镜、主体突然入画、字幕/台标出现、档案片划痕。
- **长镜头**：镜头内部有大幅运动，但没有切。
- **短镜头/快切**：0.3–0.5 秒一个镜头，边界容易漏。
- **画幅问题**：遮幅黑边、上下黑边、竖屏、变帧率。

所以 SBD 的输出不应该是“一个二值切点”，而应该是**带转场类型和置信度的区间**；工程上还要允许人 `split/merge`。

### 2.2 数据集

| 数据集 | 规模/特点 | 用途 |
|---|---|---|
| [ClipShots](https://github.com/Tangshitao/ClipShots) | 20+ 类 YouTube/微博视频，1–20 分钟，含叠化/淡入淡出/滑像 | 最常用的“难” benchmark |
| SHOT / [AutoShot](https://arxiv.org/abs/2304.06116) | 853 条短视频，11,606 个镜头标注；测试集 200 条、2,716 个边界 | 短视频快切 |
| BBC Planet Earth / RAI | 纪录片/谈话节目，画面相对静态 | 传统 benchmark，分数容易偏高 |
| OmniShotCutBench | 2026，现代 wide-domain，合成转场，覆盖 mosaic/puzzle/cube/doorway 等 | 新一代 SBD 评测 |
| HISTORIAN | 历史档案电影，带电影摄影标注 | 档案片/老片鲁棒性 |

**注意**：TransNetV2 在 BBC/RAI 上 90%+，在 ClipShots 上只有 77.9。这不是模型“退步”，而是 benchmark 难度不同。选型时一定要在自己的片种上测，不要只看论文表格。

### 2.3 方法谱系

**（A）传统/轻量：帧差 + 颜色直方图 + 阈值**

- [PySceneDetect](https://github.com/Breakthrough/PySceneDetect)（BSD-3，5.6k stars，0.7.3）是事实标准：
  - `ContentDetector`：HSV 空间加权像素变化；
  - `AdaptiveDetector`：滚动平均，抗快速运动；
  - `ThresholdDetector`：慢速淡入淡出；
  - `HistogramDetector` / `HashDetector`：直方图/感知哈希。
- 优点：快、便宜、可解释、易调阈值；缺点：对渐变、闪光、手持抖动、字幕很敏感。
- 默认 `detect-adaptive`；阈值 0.3 左右是常见起点，慢片/暗戏可降到 0.15，快切可升到 0.4。

**（B）深度学习：TransNetV2**

- [TransNetV2](https://arxiv.org/abs/2008.04838)（MIT，1.1k stars）：dilated 3D CNN，输入 100 帧，两个分类头（单帧边界/全转场帧），公开权重。
- F1：ClipShots 77.9 / BBC 96.2 / RAI 93.9。工程上最成熟的“开箱即用”ML 方案。
- 局限：训练数据以广播/纪录片为主，对域外素材（现代短视频、动画、游戏画面、档案片）不一定最优；渐变边界定位不够精细。

**（C）深度学习：AutoShot**

- [AutoShot](https://arxiv.org/abs/2304.06116)（CVPRW 2023，MIT）：用 NAS 搜 3D ConvNet/Transformer 结构；在 SHOT 上比 TransNetV2 高 4.2% F1，在 ClipShots/BBC/RAI 上分别高 1.1/0.9/1.2。
- 适合短视频/快切；代码和权重可用，但依赖较旧，工程集成成本高于 TransNetV2。

**（D）2026 新 SOTA：OmniShotCut 与 PERSIST**

- [OmniShotCut](https://arxiv.org/abs/2604.24762)（NeurIPS 2026，MIT，357 stars）：把 SBD 建模成“结构化关系预测”，同时预测镜头区间、镜头内关系、镜头间关系；用合成转场生成精确边界；新 benchmark 上 range F1 0.881，transition IoU 0.644，明显高于传统方法（0.75–0.82）。
- [PERSIST](https://arxiv.org/abs/2608.29287)（2026）：把 SBD 重新表述为“持久状态判别”——只有局部变化伴随潜在时间状态的持续更新才算新镜头，专门压制闪光、字卡、档案划痕等“高证据伪切点”。在相同召回下把伪切点减少约一半，同时匹配 TransNetV2 的水平。
- 这两个工作说明：**SBD 的下一步不是“再高 0.5 个点”，而是“可解释的边界 + 更少的伪切点 + 跨域校准”。**

### 2.4 选型建议

| 场景 | 建议 |
|---|---|
| 快速原型/长片粗切 | PySceneDetect `AdaptiveDetector`，先跑 480p 代理，阈值 0.3 起步 |
| 成片质量/离线批处理 | TransNetV2 或 OmniShotCut；GPU 推理；输出切点+转场类型+置信度 |
| 渐变/叠化多 | PySceneDetect `ThresholdDetector` + ML 复核；不要只信硬切模型 |
| 档案片/老片 | PERSIST/OmniShotCut 这类抗伪切点方法；加人工 recut |
| 短视频/广告 | AutoShot / PySceneDetect 快切参数；注意 0.3–0.5 秒镜头 |
| 生产系统 | **粗切 + 精修 + 人审**：PySceneDetect 出候选，TransNetV2/OmniShotCut 复核，UI 支持 split/merge，边界变更后重算时长与下游 |

**工程细节**：

- 用 480p、固定帧率代理做检测；原片只用于关键帧和最终导出。
- 检测前裁掉黑边/遮幅，否则直方图会被黑边稀释。
- 记录 `fps` 和 `time_base`，所有时间码用秒（浮点）+ 帧号双写，避免不同工具换算误差。
- 转场类型单独分类：cut/dissolve/fade/wipe/whip/morph；边界取转场中点。
- 输出 `manualCuts` 字段，记录人改过的切点；下游必须知道“这个边界是检测的还是人定的”。

---

## 3. 场景/段落聚合：从镜头到叙事

镜头是原子，但观众感知的单位是“场”。只给镜头表，用户还是要自己脑补段落；好的拉片报告需要场景层。

### 3.1 论文与数据集

- [MovieScenes / LGSS](https://arxiv.org/abs/2004.02678)（CVPR 2020）：150 部电影、21K 个场景段；局部到全局的多模态场景分割，融合 clip/segment/movie 三级信息。
- [MovieNet](https://arxiv.org/abs/2007.10937)（ECCV 2020）：1,100 部电影、42K 场景边界、92K 电影风格标签；是电影理解最完整的数据集之一。
- [Beyond Visual Boundaries](https://arxiv.org/abs/2608.28699)（NeurIPS 2026）：重新审视“场景分割作为 movie RAG 检索单元”是否有效；说明场景边界质量直接影响长片问答/检索。
- [Shot2Story](https://arxiv.org/abs/2312.10300)（ICLR 2025）：多镜头视频的 shot-level caption、summary、QA；强调“每个镜头的事件 + 镜头间故事线”。

### 3.2 工程做法

1. **先粗分**：按地点/人物/时间跳变、镜头 embedding 突变、对白场景切换，做初始场景边界。
2. **再用 LLM 校验**：把相邻镜头卡压成“场景候选”，让模型判断“这是同一场戏吗？边界应该前移/后移吗？”
3. **输出 scene card**：场景号、起止、地点、人物、功能（建置/冲突/转折/兑现/留白）、节拍、镜头数、平均镜长、主导景别/运镜、情绪曲线。
4. **不要过度依赖场景分割**：电影的场景边界本身有歧义（平行剪辑、交叉剪辑、闪回），报告里应允许“一个场景多个子段”。

**建议**：MVP 可以先不做自动场景分割，用“每 10–15 个镜头或每 2–4 分钟”做滑动段落，等镜头表稳定后再上场景模型。这样避免场景错误污染逐镜分析。

---

## 4. 逐镜头视听语言分析

这是整个系统最有价值、也最不可靠的部分。可靠的做法不是“让 VLM 自由写”，而是**把电影语言拆成可判定的维度，每个维度给判据、枚举、证据要求和置信度**。

### 4.1 维度体系

| 维度 | 常见取值 | 可测量代理 | 主要难点 |
|---|---|---|---|
| 景别 | 大远景/远景/全景/中景/中近景/特写/大特写 | 人脸/人物框占画高比例、主体面积 | 过肩、浅景深、无人物镜头 |
| 角度 | 平视/仰视/俯视/鸟瞰/荷兰角/过肩/主观 | 地平线、人物透视、相机俯仰 | 荷兰角与手持混叠 |
| 运镜 | 固定/推/拉/摇/移/升/降/跟/环绕/手持/变焦/移焦/航拍 | 光流、全局运动、透视变化 | 主体运动 vs 相机运动；变焦 vs 推拉 |
| 构图 | 三分/中心/对称/框架/前景遮挡/留白/视线空间 | 人脸/主体位置、边缘密度、对称性 | 风格化构图难枚举 |
| 光线 | 高调/低调/硬光/柔光/逆光/侧光/顶光/底光/自然光/实用光 | 亮度分布、对比度、方向性、色温 | 混合光、夜景、后期调色 |
| 色彩 | 冷暖/饱和/低饱和/单色/互补/色彩脚本 | 主色板、HSV 统计、对比度 | 色彩意图 vs 场景客观色 |
| 焦距/景深 | 广角/标准/长焦/浅景深/深焦/变焦 | 透视畸变、背景虚化、人脸比例 | 无法从单帧可靠恢复焦距 |
| 声音 | 对白/旁白/音乐/音效/环境/静音 | ASR、说话人分离、音频事件、能量 | 声画关系、非叙事声音 |
| 剪辑/转场 | 硬切/叠化/淡入淡出/划像/匹配剪辑/跳切/正反打/轴线 | 转场检测、镜头间相似度 | 意图判断需要上下文 |

**关键原则**：

- **景别按“人物在画框里占多大”判，不按焦段判**；没有人时按同等距离的物体换算。
- **运镜先问“整幅画面动了吗”**；人在画面里跑但机位不动，是 `static`。
- **变焦 vs 推拉**：变焦透视不变，推拉背景会“涌过来”。
- **浅景深不等于特写**；背景虚化和景别是两件事。
- **构图/光线/色彩是“判断”，不是“测量”**；必须给证据，允许 `unknown`。

### 4.2 学术进展：哪些已经可做，哪些还早

**（A）景别/运动分类：有数据、有基线，但类别体系不统一**

- [MovieNet](https://arxiv.org/abs/2007.10937)：92K 电影风格标签，景别 5 类（大特写/特写/中景/全景/远景），运动 4 类（固定/摇移/拉/推）。
- [MovieShots / SGNet](https://arxiv.org/abs/2008.03548)（ECCV 2020）：46K 镜头、7K 电影预告片；5 种景别 + 4 种运动；Subject Guidance Network 用主体/背景双流分别辅助景别和运动分类。
- [CineScale](https://doi.org/10.1016/j.dib.2021.107002)（Data in Brief 2021）：124 部完整电影、792K 帧、6 位导演、9 类景别（ECU/CU/MCU/MS/MLS/LS/ELS/前景镜头/插入镜头），按 1 fps 标注；提供 CNN 基线。这是目前最适合训练/评测景别分类的数据集之一。
- [DGME-T](https://arxiv.org/abs/2510.15725)（2025）：面向历史档案片的相机运动分类，融合光流方向网格编码，把 Video Swin 的 top-1 从 81.78% 提到 86.14%。

**（B）电影技术理解：多模态大模型（MLLM）的准确率还只有 50–70%**

- [CineTechBench](https://arxiv.org/abs/2505.15145)（2025）：7 个维度（景别、角度、构图、运镜、光线、色彩、焦距），600+ 张电影图 + 120+ 段电影片段，610 个图像 QA + 128 个视频 QA；评测 15+ MLLM。
  - 静态技术问答最好：GPT-4o 70.16%，Gemini-2.5-Pro 69.67%；开源模型平均低约 15 个百分点，InternVL3 55.25%。
  - 运镜问答最好：Gemini-2.5-Pro 56.69%；不少模型在旋转/变焦上接近随机水平。
  - 结论：**“识别技术”本身都还不稳，更不用说“解释技术为什么这样用”。**
- [CinematicVQA](https://arxiv.org/abs/2609.28813)（2026）：用 Cinematic Scene Graph 把“技术 → 视觉呈现 → 叙事功能”串起来；发现模型在“描述画面”上明显好于“识别技术”，在“叙事功能/多跳推理”上更差；CoT 对多数模型没有稳定收益，SFT 才有持续提升。
- [CineCap](https://arxiv.org/abs/2606.24636)（2026）：开放形式的“电影摄影描述”（运镜、景别、景深、构图、角度），用结构化推理 + 时空锚点 + RL 奖励（完整性/准确性/覆盖门控）提升；说明**结构化证据 + 训练**比纯 prompt 更有效。
- [CameraCLIP / cinematic language dataset](https://arxiv.org/abs/2412.12223)（2024）：20 个子类，覆盖景别、角度、运镜；用于生成侧控制，也提供了可复用的分类体系。

**（C）镜头级描述/音频描述：最接近“逐镜讲解”的任务**

- [Shot-by-Shot: Film-Grammar-Aware Training-Free Audio Description Generation](https://arxiv.org/abs/2504.01020)（ICCV 2025）：
  - 以“镜头”为基本单位，扩展相邻镜头的时序上下文，引入景别、叙事线索（thread）结构等电影语法先验；
  - 用 PySceneDetect 的 AdaptiveDetector 切镜头；不需要训练 VLM，兼容开源/闭源模型；
  - 在 training-free 方法中 SOTA，并在多个 benchmark 上超过部分 fine-tuned 方法。
  - 这是“逐镜分析 + 相邻镜头上下文 + 电影语法”的直接先例。
- [Shot2Story](https://arxiv.org/abs/2312.10300)：单镜头 caption、多镜头 summary、多镜头 QA；适合做“镜头卡 → 段落卡”的训练/评测参考。
- [Movie101](https://arxiv.org/abs/2305.12140)：中文电影 benchmark，角色感知的 movie clip narrating；对中文报告生成有参考价值。
- [SAM-S](https://arxiv.org/abs/2302.07315)：从 430 部电影的 closed caption 挖出 110K 音频事件、245 种声音；纯音频 mAP 34.76%，加入视觉信息提升约 5%。说明“声音”这一维不能只靠 ASR，需要音频事件模型。

**（D）计算电影学：从 ASL 统计到零样本大规模标注**

- 电影研究早就有“平均镜头长度（ASL）/镜头时长分布”的传统：[Cinemetrics](https://cinemetrics.uchicago.edu/) 用人工打点测量镜头时长，Cutting 等人的 [Quicker, Faster, Darker](https://doi.org/10.1068/i0441aap) 则把“镜头变短、运动变多、画面变暗”量化为好莱坞风格变迁的指标。这些指标今天仍然可以直接放进拉片报告的“风格统计”层。
- [Every Shot, Zero-Shot](https://zenodo.org/records/21935394)（Arnold & Tilton, 2026）：1,236 部剧情长片、三个语料库；用零样本模型给每个镜头打“景别”和“画面人数”标签，再统计“镜头时长—取景”的耦合。
  - 1930/40 年代好莱坞，景别对镜头时长的平均拉拽约 28.1%，2000 年代降到 9.4%；人数从 28.8% 降到 5.8%。
  - 结论不是“镜头越来越快”，而是**古典电影里“切特写=变节奏”的耦合在松动**。
  - 这给了一个重要启发：**零样本模型不需要完美，也可以做“大规模、可复现的风格统计”**；但前提是标签定义固定、统计方法透明，并且承认误差。

### 4.3 工程判断：VLM 应该怎么用

**不要让 VLM 做这些**：

- 报时间码/时长/镜头数（它会编）。
- 一次看完整部片（它会抽样、漏项、前后矛盾）。
- 自由写“氛围感/高级感/视觉冲击”（无法核对，无法汇总）。
- 在没有上下文的情况下判断“叙事功能”（它不知道前后镜头）。

**应该让 VLM 做这些**：

- 看 2–4 张关键帧 + 联系表，填**枚举**（景别/角度/运镜/构图/光线/色彩/景深）。
- 写“可核对”的画面描述：谁在画框什么位置、在做什么、光从哪来、前景/背景有什么。
- 在给定前后镜头/场景上下文时，判断这一镜的**功能**（建置/对话/反应/插入/空镜/转场/产品/字卡）。
- 给 `confidence` 和 `evidence`（哪张帧、哪个测量值支持这个判断）。
- 对不确定的维度输出 `unknown`，而不是猜一个确定值。

**推荐的两遍法**：

1. **逐镜标注**（小模型/便宜模型，批量 20–25 镜）：输出结构化 JSON，枚举 + 证据 + 置信度。
2. **段落综合**（强模型）：读镜头卡 + 统计 + 相邻关系，写段落/全片报告；不重新看所有帧。

### 4.4 镜头卡 schema（建议直接落地）

```json
{
  "shot_id": "S042",
  "start": 123.45,
  "end": 126.80,
  "duration": 3.35,
  "transition_in": "cut",
  "keyframes": ["frames/S042a.jpg", "frames/S042b.jpg"],
  "measured": {
    "motion_median": 0.8,
    "brightness": 0.42,
    "contrast": 0.31,
    "saturation": 0.38,
    "palette": ["#1b1b1b", "#c9a27a", "#6b4f3a"],
    "face_ratio": 0.18
  },
  "labels": {
    "scale": "medium-close",
    "angle": "eye-level",
    "camera": "static",
    "composition": "rule-of-thirds",
    "lighting": "low-key",
    "color": "warm",
    "dof": "shallow"
  },
  "content": {
    "subjects": ["A"],
    "action": "A 低头点烟，火光从画面右侧打亮半张脸",
    "dialogue": "……",
    "audio": ["music", "lighter-click"]
  },
  "function": {
    "scene": "S05",
    "beat": "turn",
    "emotion": "tension"
  },
  "evidence": {
    "scale": "face bbox = 38% frame height",
    "camera": "motion median 0.8 < static threshold 1.5",
    "lighting": "key from camera-left, contrast ratio ~4:1"
  },
  "confidence": {
    "scale": 0.9,
    "camera": 0.8,
    "function": 0.6
  }
}
```

这个 schema 的好处：

- 机器事实（`measured`）和模型判断（`labels`/`function`）分字段，便于追责和重跑。
- 每个判断都有 `evidence`，报告可以点回帧/时间码。
- `confidence` 让下游决定“哪些镜头需要人看/重跑”。
- `transition_in`/`scene` 让镜头表可以聚合成段落。

### 4.5 质量门（建议至少这些）

| 类别 | 检查 |
|---|---|
| 时间轴 | 镜头按序、首尾相接、从 0 到片尾；`duration = end - start` |
| 编号 | 镜号连续；split/merge 后重编号 |
| 枚举 | 景别/角度/运镜/构图/光线/色彩/景深/转场只能取词表值 |
| 证据 | 每个标签至少有一个证据（帧号/测量值/上下文） |
| 运动一致性 | 声称推/拉/摇/移/跟，但实测运动接近 0 → 拦截；声称固定但运动大 → 警告 |
| 描述质量 | 画面描述 ≥ 12 字/8 词；不含“氛围感/高级感/视觉冲击”等空话；不以“这个镜头”开头 |
| 去重 | 相邻镜头描述不能一字不差；真一样也要写出机位/动作进度差异 |
| 主体 | `subjects` 必须能在人物表/上一镜中找到；空镜必须为空 |
| 节奏 | 要么整片标，要么不标；不能只标一半 |
| 资产 | 每镜关键帧真实存在；报告里的时间码可解析 |

这些门不保证“分析对”，但能保证“看起来完成”变成“可检查地完成”。`reelbench-skills` 的实践已经证明：**质量门最该拦的是模型幻觉，而不是格式错误**。

---

## 5. Agent 设计与工程实践

### 5.1 四种形态，选哪种

| 形态 | 做法 | 优点 | 缺点 | 适用 |
|---|---|---|---|---|
| A. 单次 VLM 提问 | 整片/长片段 + prompt → 一段分析 | 快、便宜 | 时间/覆盖/一致性全不可控 | demo，不建议生产 |
| B. 确定性流水线 + VLM 标注 | CV 切分/测量 → 逐镜 VLM → 规则校验 → 报告 | 可控、可测、可扩展 | 工程量大 | **推荐** |
| C. 多 agent 分工 | 切分/测量/标注/综述/质检各一个 agent | 职责清晰、可并行 | 通信/状态复杂 | 中大型系统 |
| D. 交互式 agent | 镜头表为工具，支持问答/检索/重跑/导出 | 适合探索 | 依赖底层数据质量 | 报告之上的增值层 |

**关键判断**：长视频 agent 论文（VideoAgent、Deep Video Discovery 等）大多在解决“给定问题，找到相关片段”的**检索/QA**问题；拉片是“**分析每一个镜头**”的**覆盖/一致性**问题。两者的架构不同：

- QA agent：迭代搜索、工具调用、上下文压缩，目标是“找到证据”。
- 拉片 agent：并行 map 所有镜头、分层 reduce、质量门验收，目标是“没有漏项、没有自相矛盾”。

所以不要把 VideoAgent 的“边看边找”直接套到拉片上；拉片更适合“批处理 + 结构化中间态 + 人审”。

### 5.2 推荐架构

```
┌─────────────────────────────────────────────────────────────┐
│ 0.  ingest                                                   │
│    ffprobe / 代理转码 / 音轨分离 / 字幕提取 / 黑边检测         │
├─────────────────────────────────────────────────────────────┤
│ 1.  shot segmentation                                        │
│    PySceneDetect 粗切 → TransNetV2/OmniShotCut 复核           │
│    → 转场分类 → 人工 recut → shots.json                       │
├─────────────────────────────────────────────────────────────┤
│ 2.  shot evidence                                            │
│    关键帧（15%/50%/85%）/ 联系表 / 运动曲线 / 色彩统计         │
│    / 人脸人物 / ASR / 说话人 / 音频事件 / OCR                  │
├─────────────────────────────────────────────────────────────┤
│ 3.  shot labels (parallel, batch 20–25)                      │
│    VLM 输出枚举 + 证据 + 置信度 → 质量门 → 低置信度重跑        │
├─────────────────────────────────────────────────────────────┤
│ 4.  scene / sequence aggregation                             │
│    镜头 embedding + 地点/人物/时间 + LLM 校验 → scenes.json    │
├─────────────────────────────────────────────────────────────┤
│ 5.  report generation                                        │
│    镜头表 / 逐镜卡 / 段落综述 / 风格统计 / 时间码证据           │
├─────────────────────────────────────────────────────────────┤
│ 6.  agent tools & UI                                         │
│    search_shots / get_shot / compare / render_clip / ask      │
│    播放器联动 / 筛选 / 导出 / 人工修改                         │
└─────────────────────────────────────────────────────────────┘
```

### 5.3 上下文工程：不要把整部片塞给模型

- **镜头卡是上下文单位**：一镜 2–4 张图 + 200–400 字结构化信息，比 30 帧原始视频便宜且稳定。
- **联系表（contact sheet）**：每镜首/尾帧拼一张大图，一屏 20–25 镜；先看联系表，再对不确定的镜头看单帧。
- **批处理**：20–25 镜/批，正好一张联系表；避免长上下文漏项和“串镜”。
- **分层 reduce**：镜头卡 → 场景卡 → 全片报告；每层只读下一层的摘要。
- **缓存/幂等**：以 `video_hash + shot_hash + prompt_version` 为 key；重跑只影响变更部分。
- **强弱模型分工**：小模型做逐镜枚举，强模型做段落/全片综合；不要用旗舰模型刷 1,000 个镜头。
- **证据回链**：报告里的每个判断都能点回镜头/帧/时间码；没有证据的句子不进最终报告。

### 5.4 工具设计

建议把 agent 工具限制在“可验证的动作”上：

| 工具 | 作用 | 返回 |
|---|---|---|
| `probe_video` | 元信息/帧率/时长/音轨 | JSON |
| `detect_shots` | 切分 + 转场 + 置信度 | `shots.json` |
| `recut_shots` | split/merge/移动边界 | 新 `shots.json` + 变更记录 |
| `extract_frames` | 关键帧/联系表 | 图片路径 |
| `measure_shot` | 运动/亮度/色彩/人脸比例 | 数值 |
| `transcribe` | ASR/说话人/字幕 | 带时间码文本 |
| `detect_audio_events` | 音乐/音效/环境/静音 | 事件列表 |
| `label_shot` | VLM 逐镜标注 | 结构化 JSON |
| `validate_shots` | 质量门 | 通过/失败 + 问题列表 |
| `group_scenes` | 场景聚合 | `scenes.json` |
| `write_report` | 生成报告 | Markdown/HTML |
| `search_shots` | 按景别/人物/时间/关键词检索 | 镜头列表 |
| `render_clip` | 导出某镜/某段 | MP4 |

**不要**给 agent 一个“随便写影评”的工具；给它“读镜头卡、查统计、引用证据、生成报告”的工具。

### 5.5 人机协作

- **切点是可改的**：UI 支持在时间线上 split/merge，改完重编号、重算时长、标记 `manualCuts`。
- **标签是可改的**：低置信度镜头高亮；人改过的标签进入“人工确认”状态，后续重跑不覆盖。
- **报告是可批注的**：每个判断旁边显示证据帧/时间码；人可以接受/驳回/改写。
- **版本化**：`shots.json`、`scenes.json`、`report.md` 都进版本库；每次重跑生成新版本，保留 diff。

### 5.6 成本/延迟的量级

以 90 分钟电影、1,000–1,500 镜为例：

- 每镜 3 帧，约 3,000–4,500 张图；按每张 1K–2K image token 估算，输入约 3–9M token，输出约 0.3–0.5M token。
- 用小模型（如低价 VLM）做逐镜标注，单部片子的 API 成本大致在**几美元到几十美元**；用旗舰模型重跑会高一个量级。具体价格随 provider、图片 token 计价、是否缓存变化，这里只给量级。
- 1,000–1,500 次调用，20–30 并发、每次 3–8 秒，加上解码/抽帧，**端到端大约 10–30 分钟**是合理目标；如果要“边看边出”，需要流式/增量。
- 最大的成本往往不是 token，而是**返工**：切点错、标签不一致、报告重写。质量门和人工 recut 比换更强的模型更省钱。

---

## 6. 现有实践盘点

### 6.1 开源项目/工具

| 项目 | Star（快照） | License | 能力 | 局限 |
|---|---:|---|---|---|
| [PySceneDetect](https://github.com/Breakthrough/PySceneDetect) | 5.6k | BSD-3 | 快速切分、多种 detector、CLI/Python | 阈值敏感；渐变/闪光弱；无语义 |
| [TransNetV2](https://github.com/soCzech/TransNetV2) | 1.1k | MIT | 深度学习 SBD，开箱权重 | 老片/短视频/渐变边界一般；无转场类型 |
| [AutoShot](https://github.com/wentaozhu/AutoShot) | 267 | MIT | 短视频 SBD SOTA 级 | 依赖老；工程集成成本高 |
| [OmniShotCut](https://github.com/UVA-Computer-Vision-Lab/OmniShotCut) | 357 | MIT | 2026 SOTA，关系预测 + 新 benchmark | 很新；部署/权重需验证 |
| [reelbench-skills](https://github.com/eternityspring/reelbench-skills) | 1.2k | Apache-2.0 | ffmpeg 切分 + VLM 标注 + 15 道质量门 + 交互报告 + 同步视频 | 无 ASR/人脸识别；不评价影片好坏；ffmpeg 切分对渐变弱 |
| [lapian-notes](https://github.com/bkingfilm/lapian-notes) | 814 | MIT | 本地抽帧 + AI 分析包 + 剧情泳道/结构树/情绪曲线 + 播放器联动 | 1 fps 抽帧、非真正 SBD；依赖用户自带的 AI；质量受模型影响 |
| [screen-creative-skills](https://github.com/VanGong1999/screen-creative-skills) | 517 | MIT | 31 个影视创作/评估 skill，含剧集/故事分析 | 偏剧作/策划，不是逐镜视听语言 |
| [dsh-film-analysis](https://github.com/Raven-Jackdaw/dsh-film-analysis) | 2 | MIT | DSH 插件：自动分镜、8 维分析、标注、报告/镜头表、深度拉片流水线、21 个工具 | 极新（2026-11-03），未验证；ffmpeg 阈值切分；功能多但复杂度高 |
| [cinescope](https://github.com/roy032/cinescope) | 0 | 未声明 | 从零实现镜头/构图/人脸检测 | in progress，不建议生产 |

### 6.2 三个值得细看的实践

#### （A）reelbench-skills：把“测量/判断/验收”分开

这是目前工程上最值得抄的拉片 skill。它的核心不是“让 AI 更会看电影”，而是**让拉片结果更难胡说**：

- **机器测量**：ffmpeg 场景检测出切点，ffprobe 出时长/帧率；逐帧差分算运动曲线；每镜 15%/85% 两帧 + 联系表。
- **模型判断**：只填景别、类别、运镜、画面、节奏五个字段；词表是枚举，判据写在 `taxonomy.md`。
- **代码验收**：15 道质量门，检查时间轴连续、时长自洽、镜号、枚举、画面描述可核对/不重复、主体对账、运镜与实测运动一致、节奏完整等。
- **交付**：`shots.json` + Markdown 镜头表 + 单文件交互 HTML（播放器联动、节奏带、筛选/排序、首尾帧、分布图、质量门）。
- **实测 demo**：202.9 秒 AI 短片 → 53 镜，平均 3.83 秒，15.7 切/分钟，15 门全绿；287.4 秒英文片段 → 46 镜，平均 6.25 秒，其中有一个 46.92 秒的长镜头没有被强行切碎。

**最值得借鉴的三点**：

1. **“能量的都由代码量”**：切点、时长、运动量不让模型报。
2. **运镜对账**：声称推拉摇移但实测运动接近 0 → 直接拦；反过来只警告（主体运动也会造成帧差）。
3. **`skipped != passed`**：没有证据的质量门只能标“跳过”，不能算通过。

它的边界也很清楚：不做 ASR、不做人脸识别/角色归并、不评价影片好坏、不剪辑片段。这些不是“缺陷”，而是把系统控制在“可验证”的范围内。

#### （B）lapian-notes：把拉片做成“可编辑的笔记工作台”

`lapian-notes` 是产品形态上最成熟的参考：

- 本地导入影片，按 1 秒抽帧，生成带截图的时间轴；
- 把截图 + 字幕 + prompt 打包成 ZIP，交给任意 AI（ChatGPT/Kimi/豆包/通义/DeepSeek 等）；手动分析包模式不需要 API key，也支持填自己的 key 直连；
- AI 返回 JSON 后导回，生成**剧情泳道图、结构树、观众情绪曲线**；
- 任意时间点一键跳转播放器，“播放本段”到段落结束自动暂停，支持边播边记；
- 每个段落可编辑（段落功能、关键节拍、剧本还原、创作意图），导出 Markdown/剧本/分享长图；
- 明确警告：免费 AI 可能“偷懒”，只看开头/中间/结尾几张图；要它“完整解压并按 prompt.md 逐段分析”。

**启发**：

- 拉片不只是“分析”，还是“**看片 + 记笔记 + 回看**”的工作流；播放器联动是刚需。
- “AI 分析包”是很聪明的解耦：工具不绑定模型，用户自带 AI；代价是交互链路长、质量不可控。
- 1 fps 抽帧适合“剧作/结构”层，不适合“逐镜视听语言”层；要做后者，必须真正的 SBD + 关键帧。

#### （C）dsh-film-analysis：功能最全的 DSH 插件，但还很新

它是一个 DSH Web 插件，功能覆盖非常广：

- 画面测量：尺寸/画幅比、亮度、对比度、色温、饱和度、边缘密度、直方图、主色板；
- 8 维分析：景别/景深与焦距/角度和机位/光线和影调/色彩色调/构图/镜头运动/声音线索；
- 画面标注：三分/黄金分割、景别框、轴线、视线/运动箭头、中文标签；
- 自动拉片：ffmpeg `select='gt(scene,threshold)'` 检测切点（阈值 0.10–0.60），长镜头自动分段；
- 深度拉片：按镜头/时长切 2–4 分钟段，逐段证据化分析，滚动摘要汇总；
- 整片报告：分镜表 + 逐镜讲解 + 节奏结构 + 风格主题；token 用量/费用估算；
- 21 个 `film_*` agent 工具；内置 10 维判定标准、75 条术语判据卡、8 个理论框架、7 项质量评分卡。

**判断**：设计思路（测量 + 8 维 + 证据标签 + 质量自检）很对，但它是 2026-11-03 才创建、2 stars、没有经过独立验证；镜头检测是 ffmpeg 阈值，不是 ML SBD；功能密度高，稳定性和一致性要打个问号。**适合作为“功能清单/提示词/术语卡”的参考，不适合直接当作生产内核。**

### 6.3 商业 API/产品

| 服务 | 切分能力 | 额外能力 | 对拉片的价值 |
|---|---|---|---|
| [Google Video Intelligence](https://cloud.google.com/video-intelligence/docs/feature-shot-change) | Shot change detection，**只做突变镜头** | 标签、人脸、OCR、语音转写 | 快速拿到硬切；渐变需另做；注意文档称 2027-09 关停、迁移 Gemini |
| [Azure AI Video Indexer](https://learn.microsoft.com/en-us/azure/azure-video-indexer/scene-shot-keyframe-detection-insight) | 场景/镜头/关键帧；**突变 + 渐变** | OCR、转写、主题、人脸 | 场景+镜头+关键帧一条龙；要求至少 3 个场景 |
| [AWS Rekognition](https://docs.aws.amazon.com/rekognition/latest/dg/segments.html) | Shot segments + technical cues | 标签、人脸、内容审核 | 返回 SMPTE 时间码/帧号；适合广电/长片 |
| [Twelve Labs](https://docs.twelvelabs.io/docs/guides/segment-videos) | 自定义 segment（最多 10 种定义、20 个字段） | 结构化字段、时间戳、场景分析（含 camera angles） | 最接近“按段做结构化分析”的商业 API；但仍需自己写电影语言 prompt |
| 阿里云视觉智能 [DetectVideoShot](https://help.aliyun.com/zh/viapi/developer-reference/api-jki2om) | 返回镜头切分点 | 视频拆条 `SplitVideoParts` | 国内合规/本地化；注意该平台文档标注“停止维护” |
| [腾讯云智能拆条](https://cloud.tencent.com/document/product/266/131216) | 镜头切分 + 拆条 | 云点播集成 | 国内视频云集成 |
| [火山引擎视频分镜](https://docs.volcengine.com/docs/lake-ai-service/video-story-board) | 视频分镜算子 | AI 数据湖处理 | 国内数据湖/批处理 |
| [Adobe Premiere Scene Edit Detection](https://helpx.adobe.com/premiere-pro/using/scene-edit-detection.chromeless.html) / [DaVinci Resolve Scene Cut Detection](https://docs.imaster.org/davinci-resolve-21-manual/part-3-ingest-and-organize-media/ch.-23-using-scene-detection) | 编辑器内置场景切分 | 人工精修/时间线 | 适合“人机协作”的最后一公里 |

**共同缺口**：这些 API 给你“段 + 标签”，不给你“这段为什么用特写、光线如何服务叙事”。电影语言解释层必须自己做。

### 6.4 一个重要的产品观察

2026 年下半年，中文社区同时出现了三种路线：

1. **工程派**（reelbench）：强调测量/判断/验收分离，输出可核对的数据层。
2. **笔记派**（lapian-notes）：强调看片/记笔记/回看，输出可编辑的叙事工作台。
3. **插件派**（dsh-film-analysis）：强调“一站式”，把测量、分析、标注、报告、工具全塞进一个插件。

三者都不完整：工程派缺叙事层，笔记派缺真正的镜头切分，插件派缺验证。**机会正好在“工程派的数据层 + 笔记派的工作流 + 插件派的易用性”之间。**

---

## 7. 评测：怎么知道“拉得对”

### 7.1 分层评测

| 层 | 指标 | 数据 |
|---|---|---|
| 镜头切分 | F1 @ ±2 帧、transition IoU、伪切点率 | ClipShots/SHOT/OmniShotCutBench + 自己的片种 |
| 镜头属性 | 每个维度的 accuracy / macro-F1 | MovieNet/MovieShots/CineScale + 专家标注 |
| 镜头内容 | 描述质量（CAPability/人工 rubric）、角色/动作准确率 | Shot2Story/Movie101 |
| 段落/叙事 | 场景边界 F1、段落功能一致率 | MovieScenes + 人工 |
| 报告 | 切点/术语/证据/洞察/覆盖 五维 rubric | 10–20 部片、100–200 镜的金标 |
| Agent | 任务成功率、成本、延迟、幻觉率 | 自己的任务集 |

### 7.2 报告质量 rubric（建议）

| 维度 | 问题 | 权重（建议） |
|---|---|---|
| 事实正确 | 切点/时长/镜号/时间码是否对 | 30% |
| 术语准确 | 景别/运镜/光线/构图是否用对 | 25% |
| 证据充分 | 每个判断是否有帧/时间码/测量支撑 | 20% |
| 洞察质量 | 是否解释了“为什么这样拍/这样剪” | 15% |
| 覆盖与一致 | 是否漏镜、前后是否矛盾 | 10% |

### 7.3 评测的坑

- **benchmark 域偏移**：TransNetV2 在 BBC 上 96，不代表在你的片子上 96；一定要留自己的测试集。
- **LLM-as-judge 偏差**：模型偏爱长、流畅、术语多的回答；必须有人工 rubric 锚定。
- **“看起来完整”不等于对**：100 个镜头都填了，但 30 个景别错、20 个运镜是幻觉；质量门要能拦住“空话/模板句/运动不一致”。
- **主观性**：光线/构图/叙事功能没有唯一答案；评测要允许“合理但不同”的标注，报告应显示置信度而不是假装确定。
- **版权**：评测集不要公开传播影片帧；内部使用也要控制留存。

---

## 8. 如果要做：一个可落地的方案

### 8.1 MVP（建议 4–6 周）

**目标**：输入一部电影，输出一份“可核对、可编辑、可导出”的拉片报告。

- **Week 1：镜头表**
  - ffprobe + 代理转码 + 音轨/字幕提取 + 黑边检测；
  - PySceneDetect 粗切 + TransNetV2 复核；转场分类；
  - 关键帧（15%/50%/85%）+ 联系表；`shots.json`；人工 recut UI/CLI。
- **Week 2：逐镜标注**
  - 测量：运动/亮度/对比度/饱和度/主色板/人脸比例；
  - VLM 逐镜 JSON：景别/角度/运镜/构图/光线/色彩/景深 + 描述 + 证据 + 置信度；
  - 质量门 v1（时间轴/枚举/运动一致性/描述质量）。
- **Week 3：段落与报告**
  - 镜头 embedding + 场景聚合（先规则/LLM 校验，不追求完美）；
  - 段落卡 + 全片统计（平均镜长/切速/景别分布/色彩脚本）；
  - Markdown/HTML 报告 + CSV 镜头表。
- **Week 4：交互与评测**
  - 播放器联动、筛选/搜索、低置信度高亮、人工修改；
  - 10 部片的小型金标（每部 10–20 镜）→ 算切点 F1、属性 accuracy、报告 rubric；
  - 根据错误分布调 SBD/提示词/质量门。

### 8.2 V1（再加 4–8 周）

- ASR + 说话人分离 + 音频事件（对白/音乐/音效/静音）；
- OCR（字幕/字卡/台标）；
- 人物跟踪/角色聚类（跨镜头身份）；
- 场景/序列分析：正反打、视线匹配、轴线、节奏曲线；
- Agent Q&A：`search_shots`、`compare_shots`、`ask_film`、`render_clip`；
- 多片对比：同导演/同类型/同风格的镜头统计；
- 本地/私有部署选项（数据不外传）。

### 8.3 技术选型建议

| 层 | 建议 | 理由 |
|---|---|---|
| 解码/抽帧 | ffmpeg/ffprobe | 稳定、便宜、可控 |
| SBD | PySceneDetect 粗切 + TransNetV2/OmniShotCut 复核 | 速度 + 准确率 + 可解释 |
| 关键帧 | 首/中/尾 + 清晰度/人脸筛选 | 覆盖镜头内变化 |
| 测量 | OpenCV + 光流 + 人脸/人物检测 | 便宜、可复现 |
| ASR | Whisper large-v3 / FunASR | 中英文都可用；带时间码 |
| 说话人 | pyannote / 3D-Speaker | 对话场景必备 |
| 音频事件 | PANNs/AST/CLAP | 音乐/音效/环境声 |
| VLM | 低价 VLM 做逐镜，强模型做综合 | 成本/质量平衡 |
| 报告 | LLM + 模板 + 统计 | 结构化 + 可读 |
| 存储 | SQLite/Parquet + 对象存储 | 镜头表可查询；帧可追溯 |
| 前端 | 时间线/播放器 + 表格 | 拉片是“看片”工作流 |

### 8.4 关键设计决策（建议）

1. **镜头表是唯一事实源**：报告、CSV、HTML、Q&A 都从 `shots.json` 生成；不要各自维护一份。
2. **测量与判断分字段**：`measured` / `labels` / `function` / `evidence` / `confidence` 分开。
3. **枚举优先**：所有可汇总的维度用枚举；自由文本只用于画面描述/解释。
4. **证据强制**：没有证据的判断不进最终报告；低置信度进“待人工确认”。
5. **批处理 + 分层**：20–25 镜/批；镜头 → 场景 → 全片；不要一次吞整片。
6. **人工可改**：切点/标签/文案都可编辑；改完只重跑受影响的下游。
7. **先做“可核对”，再做“有洞察”**：前者是工具，后者是影评；工具先站住。

### 8.5 主要风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| SBD 误切/漏切 | 镜头表错，下游全错 | 粗切+复核+人工 recut；渐变单独处理 |
| VLM 幻觉 | 术语/功能胡说 | 枚举+证据+质量门；低置信度人审；专用分类器兜底 |
| 长片上下文 | 漏项/前后矛盾 | 批处理+分层摘要+镜头表检索 |
| 术语不一致 | 无法汇总/比较 | 固定词表+判据+校验 |
| 评测主观 | 不知道好不好 | 金标集+rubric+双人标注 |
| 成本/延迟 | 无法规模化 | 小模型逐镜+强模型综合+缓存 |
| 版权/合规 | 不能公开/商用 | 本地处理、帧不外传、控制留存；发布前做合规评估 |

---

## 9. 参考链接

### 论文/数据集

- [TransNet V2: An effective deep network architecture for fast shot transition detection](https://arxiv.org/abs/2008.04838)（2020）
- [AutoShot: A Short Video Dataset and State-of-the-Art Shot Boundary Detection](https://arxiv.org/abs/2304.06116)（CVPRW 2023）
- [OmniShotCut: Holistic Relational Shot Boundary Detection with Shot-Query Transformer](https://arxiv.org/abs/2604.24762)（NeurIPS 2026）
- [PERSIST: Persistent-State Discrimination for Shot Boundary Detection](https://arxiv.org/abs/2608.29287)（2026）
- [A Local-to-Global Approach to Multi-modal Movie Scene Segmentation](https://arxiv.org/abs/2004.02678)（CVPR 2020）
- [MovieNet: A Holistic Dataset for Movie Understanding](https://arxiv.org/abs/2007.10937)（ECCV 2020）
- [A Unified Framework for Shot Type Classification Based on Subject Centric Lens](https://arxiv.org/abs/2008.03548)（ECCV 2020）
- [CineScale: A dataset of cinematic shot scale in movies](https://doi.org/10.1016/j.dib.2021.107002)（Data in Brief 2021）
- [Shot2Story: A New Benchmark for Comprehensive Understanding of Multi-shot Videos](https://arxiv.org/abs/2312.10300)（ICLR 2025）
- [Movie101: A New Movie Understanding Benchmark](https://arxiv.org/abs/2305.12140)（2023）
- [CineTechBench: A Benchmark for Cinematographic Technique Understanding and Generation](https://arxiv.org/abs/2505.15145)（2025）
- [CinematicVQA: Benchmarking Film-Grammar Reasoning in Large Vision-Language Models](https://arxiv.org/abs/2609.28813)（2026）
- [CineCap: Structured Reasoning with Spatio-Temporal Anchors for Cinematographic Video Captioning](https://arxiv.org/abs/2606.24636)（2026）
- [Shot-by-Shot: Film-Grammar-Aware Training-Free Audio Description Generation](https://arxiv.org/abs/2504.01020)（ICCV 2025）
- [A dataset for Audio-Visual Sound Event Detection in Movies](https://arxiv.org/abs/2302.07315)（2023）
- [Beyond Visual Boundaries: Rethinking Scene Segmentation for Movie RAG](https://arxiv.org/abs/2608.28699)（NeurIPS 2026）
- [VideoAgent: Long-form Video Understanding with Large Language Model as Agent](https://arxiv.org/abs/2403.10517)（2024）
- [VideoAgent2: Enhancing the LLM-Based Agent System for Long-Form Video Understanding by Uncertainty-Aware CoT](https://arxiv.org/abs/2504.04471)（2025）
- [Deep Video Discovery: Agentic Search with Tool Use for Long-form Video Understanding](https://arxiv.org/abs/2505.18079)（2025）
- [VideoARM: Agentic Reasoning over Hierarchical Memory for Long-Form Video Understanding](https://arxiv.org/abs/2512.12360)（2025）
- [MetaVideoAgent: Automated Video-Agent Evolution for Long-Form Video Understanding](https://arxiv.org/abs/2608.04587)（2026）
- [DGME-T: Directional Grid Motion Encoding for Transformer-Based Historical Camera Movement Classification](https://arxiv.org/abs/2510.15725)（2025）
- [Quicker, Faster, Darker: Changes in Hollywood Film over 75 Years](https://doi.org/10.1068/i0441aap)（i-Perception 2011）
- [Every Shot, Zero-Shot: The Decoupling of Framing and Duration in Sound-Era Hollywood and Prestige Film](https://zenodo.org/records/21935394)（2026）

### 开源项目

- [PySceneDetect](https://github.com/Breakthrough/PySceneDetect)
- [TransNetV2](https://github.com/soCzech/TransNetV2)
- [AutoShot](https://github.com/wentaozhu/AutoShot)
- [OmniShotCut](https://github.com/UVA-Computer-Vision-Lab/OmniShotCut)
- [ClipShots](https://github.com/Tangshitao/ClipShots)
- [reelbench-skills](https://github.com/eternityspring/reelbench-skills)
- [lapian-notes](https://github.com/bkingfilm/lapian-notes)
- [screen-creative-skills](https://github.com/VanGong1999/screen-creative-skills)
- [dsh-film-analysis](https://github.com/Raven-Jackdaw/dsh-film-analysis)
- [cinescope](https://github.com/roy032/cinescope)

### 商业 API/产品文档

- [Google Video Intelligence: Shot change detection](https://cloud.google.com/video-intelligence/docs/feature-shot-change)
- [Azure AI Video Indexer: Scene, shot, and keyframe detection](https://learn.microsoft.com/en-us/azure/azure-video-indexer/scene-shot-keyframe-detection-insight)
- [AWS Rekognition: Detecting video segments](https://docs.aws.amazon.com/rekognition/latest/dg/segments.html)
- [Twelve Labs: Segment videos](https://docs.twelvelabs.io/docs/guides/segment-videos)
- [阿里云视觉智能：镜头解析 DetectVideoShot](https://help.aliyun.com/zh/viapi/developer-reference/api-jki2om)
- [腾讯云：智能拆条](https://cloud.tencent.com/document/product/266/131216)
- [火山引擎：视频分镜](https://docs.volcengine.com/docs/lake-ai-service/video-story-board)
- [Adobe Premiere Pro: Scene Edit Detection](https://helpx.adobe.com/premiere-pro/using/scene-edit-detection.chromeless.html)
- [DaVinci Resolve: Using Scene Detection](https://docs.imaster.org/davinci-resolve-21-manual/part-3-ingest-and-organize-media/ch.-23-using-scene-detection)

---

## 10. 调研方法与限制

- **方法**：2026-11-21 通过 arXiv API/HTML、Crossref、期刊/厂商文档和 GitHub API 检索；通读关键论文摘要与部分全文；阅读 `reelbench-skills` 的 SKILL/taxonomy/validate 实现、`dsh-film-analysis` 的 `sceneDetect` 实现；未逐一体跑所有项目。
- **Star/license**：GitHub API 快照；license 以仓库 LICENSE 为准。
- **指标**：论文 F1/accuracy 来自各自 benchmark，切分容差、数据域、标注口径不同，不能直接横向排名。
- **实践**：中文 AI 拉片工具多在 2026 年下半年出现，迭代快、验证少；本报告把它们当“设计参考”，不是“生产认证”。
- **未覆盖**：视频生成侧（FilMaster、Camera Artist 等）只作为电影语法先验参考，未展开；纯剧作拉片/剧本分析只简要提及。
- **建议下一步**：选 2–3 部目标片种（电影/剧集/短片）做 100–200 镜的金标，先验证 SBD 和 3 个最关键属性（景别/运镜/光线），再决定是否投入完整系统。
