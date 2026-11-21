# 决策：VLM 逐镜标注的第一版边界

状态：proposed

## 问题

镜头事实已经由代码测出，下一步要让模型回答“景别、角度、构图、光线、色彩、景深是什么”。调研（`docs/research/2026-11-auto-shot-analysis-survey.md`）的结论是：VLM 在识别电影技术上仍不稳（CineTechBench 上静态技术问答最好约 70%，运镜约 57%），容易把“描述”当成“识别”，也会编造时间码。

需要决定：给模型什么输入、允许它写哪些字段、如何约束枚举和证据、结果放在哪里、成本和缓存怎么处理，以及密钥怎么管理。

## 决定

1. **VLM 只写判断，不写事实**：时间码、时长、帧率、镜头数仍由代码写；VLM 只填 `labels`、`content`、`evidence`、`confidence`。
2. **输入是一帧**：第一版取镜头中点的一帧（480 宽 JPEG），而不是整段视频或整部片。单帧无法可靠判断运镜，所以 `camera` 强制为 `unknown`；有上下文后再加多帧/联系表。
3. **标签先落在独立 `labels.json`**，不直接改 `shots.json`。镜头表保持不可变；标签带 `prompt_version`、模型名、`shot_hash` 和 `provenance`，后续再按契约合并。
4. **枚举 + 证据 + 置信度**：`labels` 的每个维度只能取 `docs/taxonomy.md` 的枚举值，不确定用 `unknown`；`evidence` 至少一条可核对观察；`confidence` 每个字段 0–1。模型返回缺字段、非法枚举或 `camera != unknown` 时，该镜记为错误，不写入标签。
5. **一镜一次调用，不把整片塞进上下文**；成本/延迟用 `--limit` 控制，默认只标 20 镜，`--all` 才全量。每镜约 1k token 量级，具体随 provider 和图片 token 变化。
6. **缓存 key = `shot_hash + prompt_version + model`**：同一镜头、同一 prompt、同一模型重跑会跳过；切点变了或 prompt/model 变了才重新调用。失败按镜记录，不因一镜失败丢掉整批。
7. **provider 通过 OpenAI-compatible 接口接入**：当前用 `DEEPSEEK_API_KEY` / `DEEPSEEK_API_BASE` / `DEEPSEEK_MODEL`，从 `--env-file` 或进程环境读取。密钥不写入代码、日志、`labels.json`、`shots.json` 或 PR。
8. **第一版不评价叙事功能**：单帧和单镜上下文不足，`function` 写 `unknown`；等 M3 有前后镜头/场景上下文再补。

## 备选方案

- **让 VLM 自由写一段分析**：不可汇总、无法校验，违背镜头表契约；否决。
- **让 VLM 直接切分镜头**：单帧/双帧不可靠、贵、不可复现；SBD 继续用 CV/ML，否决。
- **把标签直接写进 `shots.json`**：字段和缓存还没稳定，先独立 artifact，等 M3 合并。
- **一次把整片/整场塞给模型**：漏项、串镜、上下文成本高；改为逐镜 + 后续分层 reduce。
- **把 key 写进配置或提交 `.env`**：不可接受；只用环境变量/本地 env 文件。

## 后果

- 第一版标签只覆盖静态维度，运镜和叙事功能为空；这是有意的能力边界。
- 逐镜调用有成本/延迟，默认只采样 20 镜；全量标注要显式 `--all`。
- `labels.json` 是中间工件，最终仍要合并进镜头表；在那之前，报告/下游需要同时读 `shots.json` 和 `labels.json`。
- 单帧会漏掉镜头内变化；M1/M2 加入多帧联系表后，质量和成本都会再变。
