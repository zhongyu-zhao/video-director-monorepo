# AGENTS.md — auto-shot 子 repo

本文件只写 auto-shot 子 repo 的规则；全局协作规则见 [`../../AGENTS.md`](../../AGENTS.md)。

## 命令

从 `agents/auto-shot/` 运行：

```bash
python3 -m unittest discover -v
python3 -m auto_shot analyze <video> --out <dir> [--detector auto] [--threshold 0.25]
python3 -m auto_shot review --shots <shots.json> --video <video> [--out review.html]
python3 -m auto_shot apply-review --shots <shots.json> --flags <review-flags.json>
python3 -m auto_shot label --shots <shots.json> --video <video> --limit 20 --env-file <env>
python3 -m auto_shot verify-short --shots <shots.json> --video <video> --window 90:600 --all --env-file <env>
python3 -m auto_shot evidence --shots <shots.json> --video <video> --out <dir> [--face]
python3 -m auto_shot scenes --shots <shots.json> [--evidence <evidence.json>] [--labels <labels.json>] --out <dir>
python3 -m auto_shot screenplay --shots <shots.json> [--labels <labels.json>] [--scenes <scenes.json>] [--asr <asr.json>] --out <dir> [--translate-zh --env-file <env>]
```

依赖和入口以 `pyproject.toml` 为准。测试不需要安装包；`ffmpeg`/`ffprobe` 缺失时集成测试自动跳过。VLM 单元测试用假客户端，不调用真实 API。

## 结构

- `auto_shot/models.py`：镜头表数据结构；字段变更先改契约决策记录。
- `auto_shot/probe.py` / `detect.py`：外部工具边界，只产出事实。
- `auto_shot/detectors.py`：ffmpeg / PySceneDetect / TransNetV2 适配器与运动路由；`detection.json` 记录选择依据。
- `auto_shot/quality.py`：确定性验收；`skipped` 不等于 `passed`。
- `auto_shot/report.py`：镜头表的一个视图，不引入新事实。
- `auto_shot/review.py`：复核页生成 + 应用人工修正；`analyze`/`verify-short` 自动刷新基础页，`review` 可嵌入 labels/scenes/evidence 和源表映射；不修改原 `shots.json`。
- `auto_shot/vlm.py` / `label.py`：VLM 客户端、逐镜标注、缓存；标签只写独立 `labels.json`。
- `auto_shot/verify.py`：<1s 边界的 VLM 同一镜头判断、保守合并、多表共享缓存；只写 `*-verified.json`。
- `auto_shot/evidence.py` / `vision.py` / `asr.py`：M1 代理、黑边、关键帧/联系表、测量、音频；人脸/ASR 可选降级。
- `auto_shot/scenes.py` / `scene_reduce.py`：M3 叙事场景 reduce、聚合、全片统计、证据回链；不写回镜头表。
- `auto_shot/screenplay.py`：ASR 台词按中点对齐到镜头/场景，组合成剧本草稿；不做说话人分离/无证据润色。
- `auto_shot/taxonomy.py`：标签枚举校验，与 `docs/taxonomy.md` 同步。
- `auto_shot/pipeline.py`：只编排，不藏业务规则。

## 规则

- 时间码、时长、帧率、镜头数、运动量只能由代码写入；VLM 只能写枚举标签、描述、功能、证据和置信度。
- 镜头表是唯一事实源；报告、HTML、问答都从它生成，不各自维护数据。VLM 标签在合并进镜头表前是独立 `labels.json`。
- 没有证据的标签进“待人工确认”，不能算完成；枚举只取词表值，不确定用 `unknown`。
- 人工改过的切点或标签标 `manual`，自动重跑不覆盖；`apply-review` 只生成新文件，不覆盖原 `shots.json`。
- 默认阈值 0.25 是召回优先的起点；降低阈值必须配合复核页，不能把低阈值结果当最终镜头表。
- 高运动素材由 auto 路由到 PySceneDetect；不静默加载 torch/TransNetV2，只有 `--prefer-neural` 或显式 `--detector transnetv2` 才用神经网络。
- 路由决策、检测器阈值语义和时延必须写进 `detection.json`；不同检测器的 threshold 不能横向比较。
- 可选检测器缺失时 auto 可以回退 ffmpeg，但必须在 notes 里说明；显式指定缺失检测器要报错，不偷偷替换。
- 单帧 VLM 标注里 `camera` 必须是 `unknown`；三帧联系表允许判断基本运镜，但不确定仍 `unknown`，不伪造运镜判断。默认走三帧。
- M1 证据写独立 `evidence.json`，不改 `shots.json`；低层测量与 VLM 语义标签分开。人脸/ASR 缺失时是 skip 不是 0。
- M3 场景优先用逐镜标签/动作做叙事 reduce（标题/摘要/连续覆盖校验）；失败才回退到标签/证据变长聚合，硬上限 30 镜/300s。场景计划不是固定 12 镜；报告统计必须从镜头表/证据/标签计算。
- 剧本台词只能来自 ASR 或人工输入，必须标“自动转写、可能听错、无说话人分离”；不给角色编造姓名。
- 短镜头兜底只处理 `<1s` 边界，`same_shot=true` 且 confidence 达阈值才合并；低置信度/错误保留边界，不能替代复核页。
- `verify-short` 不覆盖原表，合并后 `source=vlm`，并重跑质量门；多张表用重复 `--shots` 共享判定，避免按方法重复调用 VLM。
- 证据/场景产物可重跑；代理/帧/联系表是大资产，不提交 git，报告只写相对回链。
- API key 只能从 `--env-file` 或进程环境读取；不写代码、日志、README、`labels.json`、`verifications.json`、`evidence.json` 或 PR。
- 产物 schema 变更必须加 `schema_version`、更新契约 ADR，并说明迁移方式。
- 不 import `video-director` 的代码；跨 agent 只交换版本化 JSON。
- 不提交视频、帧、音频等大资产；测试用 ffmpeg 现场生成合成素材。
- 新增阶段时先问“它删掉了什么维护负担”，不要为未来可能的 provider 预先抽象。

## 相关文档

- [`README.md`](README.md)
- [`docs/architecture.md`](docs/architecture.md)
- [`docs/taxonomy.md`](docs/taxonomy.md)
- [`docs/decisions/`](docs/decisions/)
