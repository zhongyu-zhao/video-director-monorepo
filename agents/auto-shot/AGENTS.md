# AGENTS.md — auto-shot 子 repo

本文件只写 auto-shot 子 repo 的规则；全局协作规则见 [`../../AGENTS.md`](../../AGENTS.md)。

## 命令

从 `agents/auto-shot/` 运行：

```bash
python3 -m unittest discover -v
python3 -m auto_shot analyze <video> --out <dir> [--threshold 0.3]
```

依赖和入口以 `pyproject.toml` 为准。测试不需要安装包；`ffmpeg`/`ffprobe` 缺失时集成测试自动跳过。

## 结构

- `auto_shot/models.py`：镜头表数据结构；字段变更先改契约决策记录。
- `auto_shot/probe.py` / `detect.py`：外部工具边界，只产出事实。
- `auto_shot/quality.py`：确定性验收；`skipped` 不等于 `passed`。
- `auto_shot/report.py`：镜头表的一个视图，不引入新事实。
- `auto_shot/pipeline.py`：只编排，不藏业务规则。

## 规则

- 时间码、时长、帧率、镜头数、运动量只能由代码写入；VLM 只能写枚举标签、描述、功能、证据和置信度。
- 镜头表是唯一事实源；报告、CSV、HTML、问答都从它生成，不各自维护数据。
- 没有证据的标签进“待人工确认”，不能算完成；枚举只取词表值，不确定用 `unknown`。
- 人工改过的切点或标签标 `manual`，自动重跑不覆盖。
- 产物 schema 变更必须加 `schema_version`、更新契约 ADR，并说明迁移方式。
- 不 import `video-director` 的代码；跨 agent 只交换版本化 JSON。
- 不提交视频、帧、音频等大资产；测试用 ffmpeg 现场生成合成素材。
- 新增阶段时先问“它删掉了什么维护负担”，不要为未来可能的 provider 预先抽象。

## 相关文档

- [`README.md`](README.md)
- [`docs/architecture.md`](docs/architecture.md)
- [`docs/taxonomy.md`](docs/taxonomy.md)
- [`docs/decisions/`](docs/decisions/)
