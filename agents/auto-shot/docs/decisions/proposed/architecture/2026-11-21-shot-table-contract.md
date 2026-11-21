# 决策：镜头表契约

状态：proposed

## 问题

镜头表是 auto-shot 的唯一事实源，报告、CSV、HTML 和后续问答都从它生成。需要一份稳定、可版本化、能区分“机器测量”和“模型判断”的字段契约；否则下游无法判断哪些值可信、哪些需要人审，也无法做增量重跑。

## 决定

### 顶层结构

```json
{
  "schema_version": 1,
  "video": {
    "path": "input.mp4",
    "duration": 6.0,
    "fps": 25.0,
    "width": 320,
    "height": 240,
    "has_audio": false
  },
  "detector": {
    "name": "ffmpeg-scene",
    "threshold": 0.3
  },
  "shots": [],
  "manual_cuts": []
}
```

- 顶层 `schema_version` 是整数；破坏性变更加一，并附 migration 说明。
- `video` 只放事实字段，由 `probe` 写入；`path` 是输入路径，不是项目内稳定引用。
- `detector` 记录产生切点的工具和参数；换检测器或阈值必须换值，便于复现。
- `manual_cuts` 记录人改过的切点，下游必须知道“这个边界是检测的还是人定的”。

### 单个镜头

```json
{
  "shot_id": "S042",
  "start": 123.45,
  "end": 126.8,
  "duration": 3.35,
  "transition_in": "cut",
  "source": "detected",
  "keyframes": ["frames/S042-15.jpg", "frames/S042-50.jpg"],
  "measured": {
    "motion_median": 0.8,
    "brightness": 0.42,
    "contrast": 0.31,
    "saturation": 0.38,
    "palette": ["#1b1b1b", "#c9a27a", "#6b4f3a"],
    "face_ratio": 0.18
  },
  "labels": {
    "scale": "medium-close",
    "angle": "eye-level",
    "camera": "static",
    "composition": "rule-of-thirds",
    "lighting": "low-key",
    "color": "warm",
    "dof": "shallow"
  },
  "content": {
    "subjects": ["A"],
    "action": "A 低头点烟，火光从画面右侧打亮半张脸",
    "dialogue": "……",
    "audio": ["music", "lighter-click"]
  },
  "function": {
    "scene": "S05",
    "beat": "turn",
    "emotion": "tension"
  },
  "evidence": {
    "scale": "face bbox = 38% frame height",
    "camera": "motion median 0.8 < static threshold 1.5"
  },
  "confidence": {
    "scale": 0.9,
    "camera": 0.8,
    "function": 0.6
  },
  "provenance": {
    "detected_by": "ffmpeg-scene@0.3",
    "labeled_by": "vlm:provider/model@prompt-v1",
    "review": "unreviewed"
  }
}
```

### 约束

- 时间统一用秒（float，保留 3 位小数）；需要帧号时另加字段，不在同一个字段里混用两种单位。`duration = end - start`。
- 只有代码可以写 `measured`；模型只能写 `labels`、`content`、`function`、`evidence`、`confidence`。
- 枚举维度只能取词表值；不确定用 `"unknown"`，不允许猜一个确定值。词表和判据放在 `docs/taxonomy.md`，与 schema 同版本。
- 每个模型判断至少有一条 `evidence`（帧号、时间码或测量值）。没有证据的判断不进最终报告，只进“待人工确认”。
- `source` 只能是 `detected` 或 `manual`。人工修改保留 `original` 子对象，自动重跑不覆盖 `manual`。
- 首个纵切只落地 `schema_version`、`video`、`detector`、`shots`（`shot_id`、`start`、`end`、`duration`、`transition_in`、`source`）、`manual_cuts`；其余字段按需增量加入，都是 additive，不改变已有字段语义。

## 备选方案

- **全部用自由文本**：不可汇总、无法校验、无法做分布统计，否决。
- **测量和判断放同一字段**：无法追责、无法只重跑模型层，否决。
- **把报告当事实源**：任何措辞修改都会污染数据，无法增量更新，否决。
- **用数据库代替 JSON**：查询方便，但 diff、review、版本对比和迁移都更重；MVP 先用 JSON，等查询成为瓶颈再引入索引层。

## 后果

- 前期字段多、schema 和词表维护成本高；换来下游稳定、可审计、可只重跑受影响的层。
- 枚举词表和判据需要电影语言知识；首个纵切先用调研里的维度，允许 `unknown`，后续再校准。
- JSON 文件在镜头数到数千时仍然可用，但全量读取会变慢；未来可能需要 Parquet/SQLite 只读索引，镜头表仍是事实源。
