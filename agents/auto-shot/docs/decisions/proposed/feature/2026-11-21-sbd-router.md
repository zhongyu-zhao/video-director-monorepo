# 决策：多检测器与运动路由

状态：proposed

## 问题

ffmpeg 的 scene score 便宜、对清晰硬切有效，但在高速大范围运动（快速摇镜、奔跑、爆炸、快速剪辑）上会把运动当成切点，产生大量误切；在特写切宽景、色调接近时又会漏切。单一 ffmpeg 阈值无法同时满足这两类素材。

神经网络 SBD（TransNetV2 等）对运动更鲁棒，但模型加载和推理有成本/时延；PySceneDetect 的 AdaptiveDetector 比 ffmpeg 抗运动，成本又远低于神经网络。需要决定：用哪些检测器、如何自动选择、如何让选择可审计，以及失败时怎么回退。

## 决定

1. **检测器抽象**：`ffmpeg-scene`、`pyscenedetect-adaptive`（可选 content）、`transnetv2` 实现同一 `detect(path) -> cuts` 接口；`shots.json` 只记选中的 `name` 和该检测器的 threshold（语义随检测器不同）。
2. **一次 ffmpeg 扫描同时做画像和基线**：auto 先跑一次 `select='gte(scene,0)'` 拿到每帧 scene score，计算 p95、high-motion 比例（score ≥ 0.10）、0.25 阈值下的 candidate rate，并直接得到 ffmpeg 切点。低运动素材只花这一次扫描，不再跑第二个检测器。
3. **运动路由**：满足任一条件视为高运动：p95 ≥ 0.05、high-motion 比例 ≥ 0.02、时长 ≥ 60s 且 candidate rate ≥ 15/min。高运动时：
   - 默认选 PySceneDetect Adaptive（成本/质量折中）；
   - `--prefer-neural` 且 TransNetV2 可用时选 TransNetV2；
   - PySceneDetect 不可用但 TransNetV2 可用时选 TransNetV2；
   - 都不可用时回退 ffmpeg，并在 `detection.json.notes` 明确提示安装可选依赖。
4. **不静默加载神经网络**：auto 不会为了“可能更好”自动 import torch；神经网络只能通过 `--prefer-neural` 或显式 `--detector transnetv2` 使用。这样低运动/普通素材不会承担 GB 级依赖和分钟级时延。
5. **显式优先**：`--detector ffmpeg|pyscenedetect|transnetv2` 跳过路由，直接使用指定检测器；缺失依赖时报可行动的安装错误，不偷偷换方法。
6. **可审计**：每次分析写 `detection.json`，记录 requested / selected / route / reason / profile / latency / cut_count / notes；`report.md` 和 CLI 同步展示路由、耗时。`shots.json` 仍是事实源。
7. **阈值/参数按检测器记录**：ffmpeg 0.25；PySceneDetect Adaptive threshold 3.0、min_scene_len 15；TransNetV2 0.5。不同检测器的 threshold 不可横向比较，`detection.json` 是解释入口。
8. **复核闭环仍然保留**：路由减少误切，但不保证正确；低阈值/高运动结果仍需 `review` + `apply-review` 修正，修正写 `manual_cuts`。

## 备选方案

- **始终用神经网络**：高运动更稳，但每次加载 torch/模型、CPU 推理分钟级；对静态对话片是浪费。否决为默认。
- **始终用 PySceneDetect**：比 ffmpeg 稳，但仍比 ffmpeg 慢 3–4 倍；低运动素材没必要。否决为默认。
- **合并多个检测器的切点（union）**：召回高但误切也叠加，且无法解释来源；否决。
- **只调 ffmpeg 阈值**：高运动误切和低对比漏切是两类相反错误，单一阈值无法兼顾。否决。
- **用 VLM 逐切点验证**：成本高、时延大，适合作为后续低置信度兜底，不作为主检测器。

## 后果

- 高运动视频要跑两次扫描（ffmpeg 画像 + PySceneDetect/神经），时延约 3× ffmpeg；低运动视频保持一次扫描。
- PySceneDetect/TransNetV2 是可选依赖；未安装时 auto 回退 ffmpeg 并在报告里说明，不会假装已经解决高运动误切。
- 路由阈值来自一集 24 分钟动画（p95 0.089、high-motion 0.045、27 candidates/min），需要更多片种校准；`detection.json` 让每次选择可复查。
- 不同检测器的 threshold 语义不同，`shots.json` 的 `threshold` 只能作为配置快照，不能跨检测器比较。
- 复核页与 `manual_cuts` 继续作为残余错误的兜底。
