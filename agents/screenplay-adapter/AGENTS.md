# AGENTS.md — screenplay-adapter 子 repo

本文件只写 screenplay-adapter 子 repo 的规则；全局协作规则见 [`../../AGENTS.md`](../../AGENTS.md)。

## 命令

从 `agents/screenplay-adapter/` 运行：

```bash
python3 -m unittest discover -v
python3 -m screenplay_adapter adapt <novel.md> --root <dir> --title <title> [--cast cast.json]
python3 -m screenplay_adapter draft --root <dir> --env-file <env> [--scene S001]
python3 -m screenplay_adapter assemble --root <dir>
python3 -m screenplay_adapter validate --root <dir>
```

依赖和入口以 `pyproject.toml` 为准。测试不需要安装包，不访问网络；writer 用本地假 HTTP server。

## 结构

- `screenplay_adapter/source.py`：章节/段落/句子解析；字符偏移是来源锚点的基础。
- `screenplay_adapter/cast.py`：对白归属抽人物、别名合并、显式人物表。
- `screenplay_adapter/beats.py`：结构模板和节拍归属；模板是数据。
- `screenplay_adapter/plan.py`：场次/集/时长分配、覆盖、来源锚点、brief。
- `screenplay_adapter/writer.py`：逐场 prompt、OpenAI 兼容 HTTP、响应校验。
- `screenplay_adapter/draft.py`：草稿合并和统计，不写业务规则。
- `screenplay_adapter/validate.py`：确定性门；fail 阻止交付，warn 进人工复核。
- `screenplay_adapter/fountain.py`：Fountain/Markdown 视图。
- `screenplay_adapter/project.py`：项目目录 I/O、哈希、env 文件。
- `screenplay_adapter/cli.py`：`adapt` / `draft` / `assemble` / `validate`。

## 规则

- **改编计划是唯一事实源**：`adaptation.json` 决定场次边界、来源、时长、集和节拍；`screenplay.json` 只能按计划合并，不能悄悄改计划。
- **代码管边界，模型管正文**：章节/句子切分、场次分配、覆盖、时长、人物引用、格式必须由代码保证；模型只写每场动作和对白。不要让模型直接改 `adaptation.json` 或一次写整本。
- **每场必须有来源锚点**：连续句子区间 + 字符偏移。没有锚点的场不能算计划的一部分；覆盖率 fail 阻止组装。
- **人物表是硬边界**：对白说话人必须在人物表（含别名）；新角色先改人物表。自动抽取是建议值，重要项目用 `--cast` 固定。
- **人物抽取必须看引号上下文**：中文 `说/道/问/答` 在叙述里很常见，不能只靠动词抓名字；引号内的人名也不是说话人。
- **对白要标来源**：`source`（原文）、`adapted`（改写）、`invented`（新增）。新增比例是 warning，不是自动判好坏的分数。
- **时长是估算**：中文对白约 4 字/秒；只用于量级门，不能宣称精确片长。
- **草稿独立落盘**：`drafts/S*.json` 带 plan/source/prompt 指纹；计划或原文变化后旧草稿必须被拒绝，不能混用。
- **失败可定位**：错误必须带场号/字段/期望值；不要静默跳过场景。
- **API key 只从 `--env-file` 或进程环境读取**；不写代码、日志、README、`adaptation.json`、`screenplay.json` 或 PR。
- **输出可重建**：Fountain/Markdown 只是 `screenplay.json` 的视图，不维护第二份事实。
- **schema 变更**：加 `schema_version`，更新契约 ADR，说明迁移方式。
- **不提交版权文本和大产物**：小说原文、草稿、生成的剧本、`adaptations/` 不入 git；测试用合成文本。
- **不 import 其他子 repo**：跨 agent 只交换版本化 JSON；消费方自己校验。
- **新增格式/模板**：先问它删掉了什么维护负担；不要为未来可能的 provider/格式预先抽象。

## 相关文档

- [`README.md`](README.md)
- [`docs/architecture.md`](docs/architecture.md)
- [`docs/decisions/`](docs/decisions/)
