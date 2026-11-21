# 决策：复核页随最新镜头/兜底结果自动刷新

状态：proposed

## 问题

`review.html` 只能由独立的 `review` 命令生成；`analyze` 和 `verify-short` 跑完后不会更新它。结果是：

- 自动检测重跑后，页面仍指向旧镜头表；
- VLM 短镜头兜底生成 `table-N-verified.json` 后，没有对应的复核页；
- 用户无法从同一个入口判断页面代表哪个阶段，容易把旧页当成最新结果。

## 决定

1. **`analyze` 默认写/刷新 `review.html`**，页面状态为“自动检测（最新）”；`--no-review` 可关闭，供批量/测试使用。
2. **`verify-short` 为每张 verified 表写 `table-N-review.html`**，并把第一张表的页面写到输出目录的 `review.html`；状态为“VLM 短镜头兜底”。
3. **页面头显示阶段、检测器、阈值和生成时间**，这样“看起来是新的但其实旧”一眼可见；页面仍只内嵌镜头表，不引入证据/标签事实。
4. **原始页不覆盖**：如已有原始 `review.html`，升级时另存 `review-original.html`；旧 localStorage 标记仍在原页面 key 下。
5. **`review` 命令保留**并增加 `--status`，用于手工重建/对比；不替代自动刷新。
6. **不自动合并人工标记**：页面只负责看和导出；`apply-review` 仍是显式步骤。

## 备选方案

- 只修文档、让用户手动跑 `review`：不能解决“跑完 analyze/verify 后页面旧的”根因。
- 页面每次打开时从 JSON 拉取：`file://` 下受浏览器安全限制，且需要 server；保持自包含 HTML。
- 用 symlink 指向最新表：Windows/本地文件不稳定；直接写文件更简单。
- 覆盖唯一 `review.html` 且不留原始页：会丢失旧的 localStorage 标记上下文；保留 `review-original.html`。

## 后果

- 每次 `analyze` 多写一个 HTML；镜头数几百时文件几十 KB，可接受。
- 多张 detector 表时，输出目录 `review.html` 代表第一张表（通常是主 auto 结果），其余在 `table-N-review.html`；需在索引/报告里说明。
- 人工复核前应确认页面头部的阶段和时间；旧标记只对同一镜头表 key 生效。
- 本次 .hack 的根页切到 448 镜的 VLM 兜底结果，原始 465 镜保留为 `review-original.html`。
