# 决策：M1 证据层、M2 多帧标注、M3 场景与报告

状态：proposed

## 问题

到 M0/M2 为止，镜头表只有切点和基础事实；VLM 只有单帧标签，缺少可复核的画面证据、音频上下文、多帧判断、场景层和全片统计。人工无法在 30 分钟片子里逐镜回溯，也无法把“这场戏”与镜头证据连起来。

## 决定

### M1 证据层

- 用 `evidence` 命令生成独立 `evidence.json`，不改 `shots.json`：
  - `proxy-480.mp4` 代理转码；
  - `cropdetect` 检测黑边和内容区；
  - 每镜 3 个关键帧（15%/50%/85%）和一张 3×1 联系表；
  - `signalstats` 逐帧测量亮度、对比度、饱和度、色调、运动（`YDIF`），按镜聚合；
  - 人脸占比可选，依赖 OpenCV；OpenCV 5 需提供 YuNet ONNX（`--face-model`），否则缺失记 `None` + note；
  - 音频用 `silencedetect` + `volumedetect` 给出静音区间、每镜静音比和全片音量；ASR 用 `faster-whisper` 可选适配器，缺失不阻塞；
  - `media.json` 记录视频/代理/内容区/音量。
- 景别、风格等语义维度仍由 M2 的 VLM 标签给出；M1 只提供可测量的低层证据，不伪造“景别测量”。

### M2 多帧标注

- `label` 默认使用同一镜头的三帧（15%/50%/85%）联系表，而不是单帧中点；prompt 升到 `vlm-labels-v2`。
- 三帧允许判断基本运镜：机位稳定、主体微动选 `static`，不确定仍 `unknown`；不再强制所有 `camera=unknown`。
- 标签仍是独立 `labels.json`，不写回镜头表；缓存按 video identity + shot hash + prompt version + model。
- “批量 reduce”由 M3 的场景聚合承担：场景层把一组镜头的标签/测量做批次汇总，而不是把多镜塞进一次 VLM 调用。

### M3 场景与报告

- `scenes` 命令把镜头聚合成场景。首版是**确定性基线**：每 12 镜或 180s 切一个场景；边界可调，后续可用 VLM reduce 替换而不改产物形状。
- `scenes.json` 每个场景带 shot_ids、时长、镜数、标签分布、测量均值、证据联系表；`stats.json` 给全片镜头数、ASL、剪辑率、P50/P90、标签分布、亮度/运动/人脸/静音、黑边、音频事件数。
- `scenes.md` 是全片报告：统计表、场景卡、每镜时间码和联系表回链；链接相对输出目录，不复制大资产。
- 证据回链只引用 `evidence/` 下的帧/联系表；没有证据时明确留空，不伪造。

### 依赖与降级

- 核心只依赖 ffmpeg/ffprobe 和 Python 标准库。
- OpenCV（`vision` extra）用于人脸；ASR（`asr` extra）用于转写；两者缺失时写 note/None，不阻塞证据/场景。
- 不静默加载 torch/OpenCV/Whisper；只有显式 `--face`/`--asr` 才尝试。

## 备选方案

- 把测量写进 `shots.json`：会破坏“镜头表是事实源”的边界，且测量会随代理/算法变化；否决，独立证据层。
- 只做单帧 VLM：便宜但无法判断运镜/多帧一致性；M2 改为三帧。
- 用 VLM 直接切场景：需要跨镜上下文、成本高且不可复现；先确定性基线，后续 reduce。
- 每镜单独抽 3 帧：简单但 465 镜会有 1,395 次进程；用一次 select 提取，联系表按镜拼。
- 让 ASR/人脸成为硬依赖：会阻塞大多数环境；改为可选。

## 后果

- 产物更多：`evidence/`（proxy、frames、contact-sheets、evidence.json、media.json）、`scenes/`（scenes.json、stats.json、scenes.md）；下游要明确引用哪一层。
- 场景边界首版是时间/镜数基线，不是语义场景；需要后续 VLM reduce 或人工修正。
- 证据测量依赖代理分辨率；亮度/运动是相对值，不能跨片直接比较。
- 人脸/ASR 未安装时是“跳过”，不是“0”；报告必须保留 note。
- 三帧联系表让 VLM 有上下文，但仍可能误判；低置信度/单帧不可见维度继续 `unknown`。
- `.hack` 30 分钟全量证据耗时约数分钟，代理/联系表占磁盘；需要在 README 标注清理/缓存策略。
