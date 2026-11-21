# auto-shot

自动拉片子 repo：输入一部片，输出可核对、可编辑的镜头表，并在镜头事实之上做逐镜视听语言分析。

当前包含三块能力：

- **M0 镜头表**：切分镜头、生成镜头表、跑质量门、出 Markdown 报告。
- **人工复核闭环**：生成本地播放器检查页，标记误切/漏切，应用后得到修正镜头表。
- **VLM 单帧标注（M2 起步）**：逐镜取中点帧，让 VLM 填景别/角度/构图/光线/色彩/景深 + 证据 + 置信度。

场景聚合和完整的逐镜叙事分析还没有实现，路线图见 [`docs/architecture.md`](docs/architecture.md)。

## 要求

- Python 3.12+
- `ffmpeg` / `ffprobe` 6.x（M0 用 ffmpeg 场景检测作为基线切分器）
- 只有跑 `label` 时才需要 VLM API key

## 快速开始

```bash
cd agents/auto-shot

# 1) 切分镜头
python3 -m auto_shot analyze /path/to/film.mp4 --out /tmp/film-shots

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

`analyze` 的关键参数是 `--threshold`，默认 `0.25`。阈值越低召回越高，也越多闪光/快速运动造成的伪切点；低阈值结果应配合复核页使用。

```bash
python3 -m auto_shot analyze INPUT --out DIR [--threshold 0.25]
```

退出码：`0` 成功；`1` 质量门/复核/标注有失败项；`2` 输入、ffmpeg 或 API 配置错误。

## 产物

```text
out/
  shots.json              # 镜头表，唯一事实源
  quality.json            # 质量门
  report.md               # 镜头表报告
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
- `labels.json` 是独立工件，不直接改 `shots.json`；缓存 key 是 `shot_hash + prompt_version + model`。
- 默认 `--limit 20`，避免一上来就产生大量调用；`--all` 才全量标注。每镜一次调用，成本/延迟随 provider 变化。
- 模型返回非法枚举、缺字段或 `camera != unknown` 时，该镜记为错误，不影响其他镜头。

## 测试

```bash
cd agents/auto-shot
python3 -m unittest discover -v
```

集成测试会用 ffmpeg 生成硬切测试片；缺少 ffmpeg 时自动跳过。VLM 单元测试用假客户端，不会调用真实 API。

## 当前边界

- 切分器仍是 ffmpeg 帧差场景分数：漏渐变、叠化和低对比度切点，阈值降低会引入闪光伪切点。复核闭环负责修正；M1 会接可替换 SBD（PySceneDetect / TransNetV2 / OmniShotCut）。
- VLM 只做单帧静态标签；运镜、叙事功能、镜头关系还没有。
- 没有 ASR、OCR、人脸、音频事件；这些属于 M1 证据层。
- 没有场景聚合和交互报告；复核页是切点检查工具，不是完整编辑器。

## 目录

```text
auto_shot/
  cli.py       # analyze / review / apply-review / label
  pipeline.py  # M0 编排：probe -> detect -> table -> gates -> report
  probe.py     # ffprobe 媒体事实
  detect.py    # ffmpeg 场景检测
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
- 词表：[`docs/taxonomy.md`](docs/taxonomy.md)

## 与其他子 repo 的边界

auto-shot 不 import `video-director` 的代码。需要把镜头表交给下游时，只通过版本化 JSON 文件；消费方自己校验，不共享内部模型。仓库级约定见 [`../../AGENTS.md`](../../AGENTS.md)。
