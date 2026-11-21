# auto-shot

自动拉片子 repo：输入一部片，输出可核对、可编辑的镜头表，并在镜头事实之上做逐镜视听语言分析。

当前包含三块能力：

- **M0 镜头表**：切分镜头、生成镜头表、跑质量门、出 Markdown 报告。
- **多检测器 + 运动路由**：ffmpeg、PySceneDetect、TransNetV2 三种切分器，按素材运动量自动选择。
- **人工复核闭环**：生成本地播放器检查页，标记误切/漏切，应用后得到修正镜头表。
- **VLM 单帧标注（M2 起步）**：逐镜取中点帧，让 VLM 填景别/角度/构图/光线/色彩/景深 + 证据 + 置信度。

场景聚合和完整的逐镜叙事分析还没有实现，路线图见 [`docs/architecture.md`](docs/architecture.md)。

## 要求

- Python 3.12+
- `ffmpeg` / `ffprobe` 6.x（ffmpeg 是默认检测器和图片/代理工具）
- 只有跑 `label` 时才需要 VLM API key
- 高运动素材可选安装 PySceneDetect/TransNetV2 检测器（见下）

## 快速开始

```bash
cd agents/auto-shot

# 1) 切分镜头（auto 按运动量选择检测器）
python3 -m auto_shot analyze /path/to/film.mp4 --out /tmp/film-shots --detector auto

# 2) 人工复核切点（浏览器打开 review.html）
python3 -m auto_shot review \
  --shots /tmp/film-shots/shots.json \
  --video /path/to/film.mp4

# 3) 把页面导出的 review-flags.json 应用成修正镜头表
python3 -m auto_shot apply-review \
  --shots /tmp/film-shots/shots.json \
  --flags /tmp/film-shots/review-flags.json \
  --out /tmp/film-shots/shots-reviewed.json

# 4) VLM 逐镜标注（默认只标 20 镜，先采样）
python3 -m auto_shot label \
  --shots /tmp/film-shots/shots.json \
  --video /path/to/film.mp4 \
  --out /tmp/film-shots \
  --limit 20 \
  --env-file /path/to/.env
```

`analyze` 的关键参数是 `--detector` 和 `--threshold`：

```bash
python3 -m auto_shot analyze INPUT --out DIR [--detector auto] [--threshold 0.25] [--prefer-neural]
```

`--threshold` 是 ffmpeg 的 scene score 阈值，默认 `0.25`。阈值越低召回越高，也越多闪光/快速运动造成的伪切点；低阈值结果应配合复核页使用。其他检测器有自己的阈值，记录在 `detection.json`。

## 检测器与自动路由

| 方法 | 特点 | 依赖 | 本集实测（23:42, 720p） |
|---|---|---|---|
| `ffmpeg` | 最快；清晰硬切好；高速运动易误切 | ffmpeg | 624 镜，约 15s |
| `pyscenedetect` | AdaptiveDetector 抗运动；成本中等 | `scenedetect` + OpenCV | 384 切，约 47s |
| `transnetv2` | 神经网络；运动/渐变更稳；CPU 推理慢 | `transnetv2-pytorch` + torch | 60s 片段 10.8s，约 20 切 |

`auto` 先用一次 ffmpeg 扫描得到每帧 scene score，计算 p95、高运动比例和 candidate rate：

- 低运动：直接用这次扫描的 ffmpeg 切点，不跑第二个检测器。
- 高运动（p95 ≥ 0.05 或高运动比例 ≥ 0.02 或时长 ≥ 60s 且 candidate rate ≥ 15/min）：优先 PySceneDetect Adaptive；`--prefer-neural` 时用 TransNetV2；都没有则回退 ffmpeg，并在 `detection.json.notes` 提示安装可选依赖。
- `auto` 不会静默加载神经网络；torch/模型只在显式或 `--prefer-neural` 时导入。

安装可选检测器：

```bash
cd agents/auto-shot
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[sbd]'     # PySceneDetect
pip install -e '.[neural]'  # TransNetV2 + torch（CPU 可用，体积较大）
# CPU-only torch：pip install torch --index-url https://download.pytorch.org/whl/cpu
```

显式指定检测器会跳过路由：`--detector ffmpeg|pyscenedetect|transnetv2`。缺少依赖时报可行动的安装错误。

退出码：`0` 成功；`1` 质量门/复核/标注有失败项；`2` 输入、ffmpeg 或 API 配置错误。

## 产物

```text
out/
  shots.json              # 镜头表，唯一事实源
  quality.json            # 质量门
  report.md               # 镜头表报告
  detection.json          # requested/selected/route/profile/latency/notes
  review.html             # 本地复核页（review 生成）
  review-flags.json       # 页面导出：误切/漏切
  shots-reviewed.json     # 应用复核后的镜头表（原 shots.json 不变）
  shots-reviewed-report.md
  labels.json             # VLM 逐镜标签（带缓存/provenance）
  labels.md               # 标签的人读视图
  frames/                 # 标注用的关键帧
```

## 复核页怎么用

`review.html` 左侧是播放器，右侧是全部镜头：

- 点击镜头或按 `←`/`→` 跳到该切点前 0.6 秒播放；空格暂停。
- 切点前后其实是同一镜时，勾选该行的“误切”。
- 播放到漏掉的切点时，按 `m` 或“标记漏切”。
- 标记只存浏览器 `localStorage`；用“导出标记 JSON”生成 `review-flags.json`。
- `apply-review` 会把误切并入前一镜、把漏切拆开，重编号并写入 `manual_cuts`，然后重跑质量门。

## VLM 标注

- 密钥从 `--env-file` 或进程环境读取，变量名默认 `DEEPSEEK_API_KEY`；`--base-url` / `--model` 可覆盖。密钥不进代码、日志或产物。
- 第一版只取镜头中点的一帧，单帧无法可靠判断运镜，所以 `camera` 固定为 `unknown`；`function` 也没有上下文，先写 `unknown`。
- `labels.json` 是独立工件，不直接改 `shots.json`；缓存 key 是 `video identity + shot_hash + prompt_version + model`。
- 默认 `--limit 20`，避免一上来就产生大量调用；`--all` 才全量标注。每镜一次调用，成本/延迟随 provider 变化。
- 模型返回非法枚举、缺字段或 `camera != unknown` 时，该镜记为错误，不影响其他镜头。

## 测试

```bash
cd agents/auto-shot
python3 -m unittest discover -v
```

集成测试会用 ffmpeg 生成硬切测试片；缺少 ffmpeg 时自动跳过。VLM 单元测试用假客户端，不会调用真实 API。

## 当前边界

- auto 路由能减少高运动误切，但不保证正确；低对比度切点/渐变仍可能漏，复核闭环负责修正。路由阈值来自一集素材，其他片种需要校准。
- VLM 只做单帧静态标签；运镜、叙事功能、镜头关系还没有。
- 没有 ASR、OCR、人脸、音频事件；这些属于 M1 证据层。
- 没有场景聚合和交互报告；复核页是切点检查工具，不是完整编辑器。

## 目录

```text
auto_shot/
  cli.py       # analyze / review / apply-review / label
  pipeline.py  # M0 编排：probe -> detect -> table -> gates -> report
  probe.py     # ffprobe 媒体事实
  detect.py    # ffmpeg 场景检测底层
  detectors.py # ffmpeg / PySceneDetect / TransNetV2 + 运动路由
  models.py    # 镜头表数据结构与 JSON 读写
  quality.py   # 质量门
  report.py    # Markdown 报告
  review.py    # 复核 HTML 生成 + 应用修正
  label.py     # VLM 逐镜标注编排与缓存
  vlm.py       # OpenAI-compatible VLM 客户端 / env 读取
  taxonomy.py  # 标签枚举校验
tests/         # 单元测试 + 合成视频集成测试
docs/          # 架构、词表、决策记录
```

## 文档

- 架构与路线图：[`docs/architecture.md`](docs/architecture.md)
- 镜头表契约：[`docs/decisions/proposed/architecture/2026-11-21-shot-table-contract.md`](docs/decisions/proposed/architecture/2026-11-21-shot-table-contract.md)
- 四层流水线：[`docs/decisions/proposed/architecture/2026-11-21-auto-shot-pipeline.md`](docs/decisions/proposed/architecture/2026-11-21-auto-shot-pipeline.md)
- 人工复核闭环：[`docs/decisions/proposed/feature/2026-11-21-human-review-loop.md`](docs/decisions/proposed/feature/2026-11-21-human-review-loop.md)
- VLM 标注边界：[`docs/decisions/proposed/feature/2026-11-21-vlm-shot-labeling.md`](docs/decisions/proposed/feature/2026-11-21-vlm-shot-labeling.md)
- 多检测器与路由：[`docs/decisions/proposed/feature/2026-11-21-sbd-router.md`](docs/decisions/proposed/feature/2026-11-21-sbd-router.md)
- 词表：[`docs/taxonomy.md`](docs/taxonomy.md)

## 与其他子 repo 的边界

auto-shot 不 import `video-director` 的代码。需要把镜头表交给下游时，只通过版本化 JSON 文件；消费方自己校验，不共享内部模型。仓库级约定见 [`../../AGENTS.md`](../../AGENTS.md)。
