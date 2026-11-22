# 示例：《基督山伯爵》20 分钟开场

这是一个用 `screenplay-adapter` 走完整条流水线产出的 20 分钟开场示例：10 场、约 18.7 分钟（估算）、0 个 fail 门、1 个 expected warning。

先读剧本：[`screenplay.md`](screenplay.md)（Fountain 版：[`screenplay.fountain`](screenplay.fountain)）。也可以直接在本目录重跑验收：

```bash
cd agents/screenplay-adapter
python3 -m screenplay_adapter validate --root examples/count-of-monte-cristo-opening
```

## 这是什么

- **源文本**：一份 10 节的中文 beat treatment（[`source/source.md`](source/source.md)），由《基督山伯爵》前七章的公开情节压缩而成，不是原著译文。
- **计划**：[`adaptation.json`](adaptation.json)，10 场，每场 120 秒目标，来源锚点覆盖 10 节 treatment。
- **人物表**：[`cast.json`](cast.json)，显式指定 10 个角色和别名，避免中文对白归属漏抽。
- **写作**：[`drafts/`](drafts/) 里是逐场 JSON 草稿。这个示例的草稿由 agent 按 brief 手写，用来演示“代码管结构、写作者管正文”的分工；不是调用外部模型生成。
- **验收**：[`report.json`](report.json)，`warn`，0 fail。唯一 warning 是 67% 对白标记为 `invented`——因为源文本只是 beat treatment，扩写必然新增大量对白。这正是报告要提示人审的地方，不是失败。
- **导出**：[`screenplay.md`](screenplay.md) 和 [`screenplay.fountain`](screenplay.fountain) 都从 [`screenplay.json`](screenplay.json) 重建。

## 怎么复现

```bash
cd agents/screenplay-adapter

# 1) 从 treatment 和显式人物表重建设计划
python3 -m screenplay_adapter adapt \
  examples/count-of-monte-cristo-opening/source/source.md \
  --root /tmp/monte-cristo \
  --title '基督山伯爵：马赛（20 分钟开场）' \
  --format series \
  --episodes 1 \
  --episode-minutes 20 \
  --scene-seconds 120 \
  --language zh \
  --mode expand \
  --aspect horizontal \
  --genre '剧情/复仇' \
  --logline '一个即将成为船长和丈夫的年轻人，在订婚宴上被一封匿名信推进了十四年的深渊。' \
  --cast examples/count-of-monte-cristo-opening/cast.json

# 2) 把本目录的 drafts/ 复制到 /tmp/monte-cristo/drafts/
# 3) 合并并验收
python3 -m screenplay_adapter assemble --root /tmp/monte-cristo
```

`drafts/` 里的 plan/source 指纹与本次计划匹配；改 source、cast 或 brief 后需要重新生成草稿，否则 `assemble` 会拒绝。

## 来源与版权

- 故事来自 Alexandre Dumas 的 *Le Comte de Monte-Cristo*（1844），已进入公有领域。
- 本示例的 treatment 是 agent 根据 [Wikisource: The Count of Monte-Cristo, Volume 1](https://en.wikisource.org/wiki/The_Count_of_Monte-Cristo/Volume_1) 前七章的公开情节重写的中文梗概，没有复制 1888 年英译本或任何现代中译本的正文。
- 剧本正文是本示例的一部分，采用与仓库相同的 MIT 许可；它是一次工具演示，不是制作定稿。

## 已知边界

- 这是 20 分钟开场，不是完整长片；结尾停在伊夫堡，字幕“十四年后”。
- 对白大多为扩写新增，人物声音、节奏和场面调度的最终判断仍要人读。
- 时长是启发式估算（中文对白约 4 字/秒），不是精确片长。
