# auto-shot 架构与路线图

本文写当前实现和计划中的结构。为什么这样分层见 [`docs/decisions/proposed/architecture/2026-11-21-auto-shot-pipeline.md`](decisions/proposed/architecture/2026-11-21-auto-shot-pipeline.md)；本文不重复论证。

## 目标

输入一部电影/剧集/短片，输出“可核对、可编辑、可导出”的镜头表和逐镜视听语言分析。镜头表是唯一事实源，报告只是它的一个视图。

## 当前流水线

```text
input.mp4
   │
   ├─ probe      ffprobe：时长/帧率/画幅/音轨          ──► media facts
   ├─ route      ffmpeg 全帧 scene score → 运动画像     ──► detection.json
   ├─ detect     ffmpeg / PySceneDetect / TransNetV2    ──► cuts
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
| `detect.py` | ffmpeg 场景检测底层 / 全帧分数扫描 | 已有 |
| `detectors.py` | 多检测器适配 + 运动路由 | 已有 |
| `models.py` | 镜头表数据结构与 JSON 读写 | 已有 |
| `quality.py` | 确定性质量门 | 已有 |
| `report.py` | Markdown 镜头表 | 已有 |
| `pipeline.py` | 串起分析阶段 | 已有 |
| `review.py` | 复核 HTML 生成 + 应用人工修正 | 已有 |
| `taxonomy.py` | 标签枚举校验 | 已有 |
| `vlm.py` / `label.py` | VLM 客户端、逐镜标注、缓存 | 三帧 |
| `verify.py` | <1s 边界的 VLM 同一镜头判断与合并 | 已有 |
| `evidence.py` / `vision.py` / `asr.py` | 代理、黑边、关键帧/联系表、测量、音频；人脸/ASR 可选 | 已有 |
| `scenes.py` / `scene_reduce.py` | 叙事场景 reduce、聚合、统计、证据回链 | 已有 |

## 产物

```text
out/
  shots.json              # schema_version, video, detector, shots, manual_cuts
  quality.json            # ok, checks[]
  detection.json          # requested/selected/route/profile/latency/notes
  report.md               # 人读的镜头表视图
  review.html             # 单文件复核页
  review-flags.json       # 页面导出：falseCuts / missedCuts
  shots-reviewed.json     # 应用复核后的镜头表
  shots-reviewed-report.md
  labels.json             # VLM 标签：labels/content/evidence/confidence/provenance
  labels.md               # 标签的人读视图
  frames/                 # 标注用关键帧
  vlm-verify/
    verifications.json    # 短镜头边界判定与缓存
    table-N-verified.json # 多张表应用合并后的结果
    verification-report.md
  evidence/
    proxy-480.mp4
    media.json
    frames/S001-k1.jpg
    contact-sheets/S001.jpg
    evidence.json
  scenes/
    scenes.json
    stats.json
    scenes.md
```

字段契约见 [`2026-11-21-shot-table-contract.md`](decisions/proposed/architecture/2026-11-21-shot-table-contract.md)。镜头表保持事实层；VLM 标签先放 `labels.json`，等字段稳定后再合并进镜头表。

## 检测器与运动路由

`--detector auto` 先跑一次 ffmpeg 全帧 scene score 扫描，同时得到运动画像和基线切点。低运动素材直接用这次扫描的 ffmpeg 切点；高运动素材转为 PySceneDetect Adaptive（可选 `--prefer-neural` 转 TransNetV2）。高运动判据：p95 ≥ 0.05、score ≥ 0.10 的帧占比 ≥ 0.02，或时长 ≥ 60s 且 candidate rate ≥ 15/min。

本集（23:41.994，720p）实测：

| 检测器 | 切点数 | 时延 |
|---|---:|---:|
| ffmpeg（0.25） | 624 | 14.9s |
| PySceneDetect Adaptive（auto 选中） | 384 | 47.0s |
| TransNetV2（60s 片段） | 约 20 | 10.8s（含模型加载） |

`auto` 不静默加载 torch：神经网络只在 `--prefer-neural` 或显式 `--detector transnetv2` 时使用；PySceneDetect 缺失时回退 ffmpeg 并在 `detection.json.notes` 说明。不同检测器的 threshold 语义不同（ffmpeg scene score / PySceneDetect adaptive threshold / TransNetV2 概率），`shots.json` 里的 threshold 只是配置快照。详见 [`2026-11-21-sbd-router.md`](decisions/proposed/feature/2026-11-21-sbd-router.md)。

## 切点复核闭环

默认阈值是 0.25，比最初的 0.3 召回更高；代价是闪光、黑场和快速运动会带来伪切点，而低对比度的特写→宽景切点仍可能漏掉。复核页用于处理这两类错误：

- `review` 生成单文件 HTML，播放器 + 镜头列表；点击/←→跳到切点前 0.6s。
- 页面可勾选误切、按 `m` 记录漏切；标记在 `localStorage`，导出 `review-flags.json`。
- `apply-review` 将误切并入前一镜、漏切拆开，重编号，写入 `manual_cuts`，再跑质量门。
- 原 `shots.json` 不被覆盖；修正结果另存，随时可对比/回退。

为什么不是纯调阈值：同一集从 0.3 的 508 镜降到 0.25 的 624 镜，降低阈值会增加召回也会引入伪切点，单靠阈值无法兼顾。详见 [`2026-11-21-human-review-loop.md`](decisions/proposed/feature/2026-11-21-human-review-loop.md)。

## VLM 标签

第一版只给模型一帧（镜头中点，480 宽），要求输出：

- `labels`：景别/角度/运镜/构图/光线/色彩/景深，只能取词表枚举值；单帧仍 `unknown`，三帧可判断基本运镜。
- `content`：主体 + 一句可核对的动作描述。
- `evidence`：至少一条观察依据。
- `confidence`：每个维度 0–1。

标签写入独立 `labels.json`，带 `shot_hash`、`prompt_version`、模型名和 `provenance`；缓存 key 是 `video identity + shot_hash + prompt_version + model`。模型返回非法枚举、缺字段或伪造运镜时，该镜记为错误，不写入标签。详见 [`2026-11-21-vlm-shot-labeling.md`](decisions/proposed/feature/2026-11-21-vlm-shot-labeling.md)。

## M1 证据 / M2 多帧 / M3 场景

- **M1**：`evidence` 生成代理、黑边/内容区、每镜 3 帧和联系表、亮度/对比度/饱和度/色调/运动测量、静音/音量事件；人脸和 ASR 走可选适配器，缺失是 skip。测量写独立 `evidence.json`，不回写镜头表。
- **M2**：`label` 默认用三帧联系表（15%/50%/85%），prompt `vlm-labels-v2`；三帧允许判断基本运镜，不确定仍 `unknown`。场景层把一组镜头的标签/测量做批量 reduce。
- **M3**：`scenes` 默认把逐镜标签/动作交给 VLM 做叙事 reduce，返回连续场景计划（标题/摘要/边界理由）；覆盖校验失败才回退到标签/证据变长聚合。场景卡、全片统计和证据回链保留。

## 短镜头 VLM 兜底

`verify-short` 只对 `<1s` shot 的入点/出点取切点前后帧，让 VLM 判断是否同一镜头；只有 `same_shot=true` 且 confidence ≥ 0.70 才合并。多张表可一次传入，按 0.12s 聚类共享判定；结果写 `*-verified.json`，原表不动，`source=vlm`。低置信度/模型错误保留边界，人工复核仍是最终兜底。

`.hack` 1:30–10:00 实测（相对人工复核的 PySceneDetect 切点集）：

| 方法 | 过滤前 P/R/F1 | 过滤后 P/R/F1 | 移除边界 |
|---|---|---|---:|
| PySceneDetect | 0.753 / 1.000 / 0.859 | 0.908 / 0.986 / 0.945 | 17 |
| ffmpeg 0.25 | 0.711 / 0.914 / 0.800 | 0.886 / 0.886 / 0.886 | 20 |

42 次 VLM 调用（2 并发，约 1 分钟），25 个边界判为 same。详见 [`2026-11-21-vlm-short-cut-verifier.md`](decisions/proposed/feature/2026-11-21-vlm-short-cut-verifier.md)。

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
- **多检测器与路由（已完成）**：ffmpeg/PySceneDetect/TransNetV2 适配，按运动画像自动路由，`detection.json` 记录选择与耗时。
- **人工复核闭环（已完成）**：review HTML、误切/漏切标记、apply-review、manual_cuts；analyze/verify-short 自动刷新基础页，review 可嵌入标签/场景/证据。
- **VLM 逐镜标注（三帧起步）**：三帧联系表 + 证据 + 置信度；上下文/叙事功能仍待补。
- **VLM 短镜头兜底（已完成）**：<1s 边界的前后帧判断、保守合并、多表共享缓存；>1s 误切仍靠复核。
- **M1 证据（已完成）**：代理/黑边/关键帧/测量/音频。
- **M2 多帧标注（已完成）**：三帧联系表，允许基本运镜判断。
- **M3 场景与报告（已完成基线）**：场景卡、全片统计、证据回链；场景边界仍是固定基线。
- **M4 交互与问答**：`search_shots`、`compare_shots`、`render_clip`、播放器联动、增量重跑。

三帧 VLM 仍是窄切片：先验证“多帧标签/证据/缓存/密钥边界”能跑通，不宣称已经解决视听语言理解。

## 与其他子 repo 的边界

- 不 import `video-director` 的代码。
- 需要把镜头表交给 video-director 时，导出 `shots.json`（或 `shots-reviewed.json`），由下游按自己的契约校验。
- 共享的是版本化 JSON，不是 Python 类型或内部模块。

## 非目标

- 不生成或剪辑视频。
- 不写影评、不做“一键拉片”的叙事结论。
- 检测/测量不依赖商业 API；VLM provider 可替换，不写入事实层。
- 不把整片塞进单次模型调用。
