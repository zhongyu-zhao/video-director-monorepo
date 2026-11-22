# 决策：改编计划、草稿、剧本与报告的 JSON 契约

状态：proposed

## 问题

`screenplay-adapter` 有四类工件：改编计划、逐场草稿、合并剧本、验收报告。它们会被 CLI、测试、人工审阅和下游 video-director 消费。如果没有稳定的字段契约：

- 场次来源、人物和对白来源无法校验；
- 计划或原文变化后旧草稿会被静默复用；
- Fountain/Markdown 与 JSON 可能各说各话；
- 下游无法判断自己读到的是哪个 schema。

需要决定：每类工件的字段、不变量、哈希和迁移规则。

## 决定

所有 JSON 顶层都带 `schema_version`（当前 `1`）和 `kind`。字段名用 snake_case；中文文本保持 UTF-8，不转义；时间用秒，保留 3 位小数。

### 1. `adaptation.json`（计划，事实源）

```json
{
  "schema_version": 1,
  "kind": "screenplay-adapter-plan",
  "title": "雨夜",
  "brief": {
    "title": "雨夜",
    "format": "short-drama",
    "episodes": 30,
    "episode_minutes": 2.0,
    "scene_seconds": 45.0,
    "total_minutes": 60.0,
    "total_seconds": 3600.0,
    "genre": "",
    "logline": "",
    "audience": "",
    "aspect": "vertical",
    "language": "zh",
    "mode": "adapt"
  },
  "source": {
    "path": "source/source.md",
    "sha256": "…",
    "title": "雨夜",
    "language": "zh",
    "chars": 479,
    "word_units": 359,
    "chapter_count": 3,
    "paragraph_count": 15,
    "sentence_count": 24,
    "chapters": [{"id": "CH001", "index": 1, "title": "第一章 咖啡馆", "chars": 172, "paragraph_count": 5, "sentence_count": 9}]
  },
  "cast": [
    {"id": "C001", "name": "林昭", "aliases": [], "first_chapter": "CH001", "last_chapter": "CH003",
     "mentions": 7, "dialogue_mentions": 2, "source": "auto", "role": "", "note": ""}
  ],
  "scenes": [
    {
      "id": "S001", "episode": 1, "index_in_episode": 1,
      "beat": "hook", "beat_label": "开场钩子", "duration_s": 45.0,
      "source": {
        "sentence_start": 0, "sentence_end": 2,
        "char_start": 19, "char_end": 120,
        "chapter_ids": ["CH001"], "paragraph_ids": ["P0001", "P0002"],
        "excerpt": "林昭推开咖啡馆的门……"
      },
      "cast": ["林昭", "顾远"],
      "expansion": ["add_dialogue"],
      "notes": ["原文没有直接引语……"]
    }
  ],
  "requested_scenes": 8,
  "plan_hash": "…",
  "warnings": []
}
```

字段约束：

- `brief.format` ∈ `feature | series | short-drama`；`feature` 只允许 1 集；`episodes ≥ 1`；时长 > 0。
- `source.path` 固定为项目内相对路径；`source.sha256` 是规范化文本的 SHA-256。
- 句子/字符偏移指向 `source/source.md`；`sentence_start..sentence_end` 是闭区间。
- `scenes` 必须按 `S001...` 连续编号，`episode` 单调，`index_in_episode` 从 1 连续。
- `cast` 的 `name` 是说话人匹配用的主名；`aliases` 也参与匹配；`source` ∈ `auto | explicit`。
- `expansion` 是提示码（`compress` / `expand` / `add_dialogue` / `establish_cast` / `crowded_cast` / `split_scene`），不是内容判断。
- `requested_scenes` 是按目标时长算出的期望场数；实际场数可能因源太稀疏而更少，此时 `warnings` 必须说明。

**计划哈希**：

```text
plan_hash = sha256(canonical_json({
  "source_sha256": source.sha256,
  "brief": brief,
  "cast": cast,
  "scenes": scenes
}))
```

canonical JSON 用 `ensure_ascii=False, sort_keys=True, separators=(",", ":")`。哈希不包含 `warnings`/`requested_scenes`，避免非结构信息导致草稿失效；场次、人物表或 brief 变化必须失效。

### 2. `drafts/S001.json`（逐场草稿）

```json
{
  "schema_version": 1,
  "scene_id": "S001",
  "heading": {"int_ext": "INT", "location": "咖啡馆", "time": "NIGHT"},
  "action": ["雨水敲打玻璃。林昭把伞靠在墙边。"],
  "dialogue": [
    {"character": "林昭", "parenthetical": "低声", "line": "我来了。", "basis": "adapted"}
  ],
  "transition": "",
  "plan_hash": "…",
  "source_sha256": "…",
  "writer": {"provider": "openai-compatible", "model": "gpt-4o-mini"},
  "prompt_sha256": "…",
  "notes": ""
}
```

- `heading.int_ext` ∈ `INT | EXT | INT/EXT`；`time` ∈ `DAY | NIGHT | DAWN | DUSK | MORNING | EVENING | CONTINUOUS | LATER | UNKNOWN`。
- `action` 至少一个块或 `dialogue` 至少一句；空场不能通过验收。
- `basis` ∈ `source | adapted | invented`；`source` 表示原文有对应台词，`adapted` 表示由原文改写，`invented` 表示新增。
- `plan_hash` / `source_sha256` 必须匹配当前计划；合并时不一致直接拒绝，不静默覆盖。
- 草稿按场独立，允许只写一部分；缺失场在 `assemble` 时报错。

### 3. `screenplay.json`（合并剧本，事实源）

```json
{
  "schema_version": 1,
  "kind": "screenplay",
  "title": "雨夜",
  "plan_hash": "…",
  "source_sha256": "…",
  "stats": {
    "scene_count": 8, "episode_count": 3,
    "dialogue_lines": 8, "action_blocks": 8,
    "characters_speaking": ["林昭", "顾远"],
    "dialogue_basis": {"source": 0, "adapted": 8, "invented": 0},
    "estimated_seconds": 55.2, "target_seconds": 360.0,
    "average_scene_seconds": 6.9
  },
  "scenes": [
    {
      "id": "S001", "episode": 1, "index_in_episode": 1,
      "beat": "hook", "beat_label": "开场钩子",
      "target_seconds": 45.0, "estimated_seconds": 6.9,
      "heading": {"int_ext": "INT", "location": "咖啡馆", "time": "NIGHT"},
      "action": ["…"],
      "dialogue": [{"character": "林昭", "parenthetical": "低声", "line": "我来了。", "basis": "adapted"}],
      "transition": "",
      "source": {"sentence_start": 0, "sentence_end": 2, "…": "…"},
      "writer": {"provider": "openai-compatible", "model": "gpt-4o-mini"},
      "notes": ""
    }
  ]
}
```

- `scenes` 的顺序和数量必须与计划一致；`source` 从计划复制，不允许草稿改锚点。
- `target_seconds` 来自计划，`estimated_seconds` 是启发式估算；两者都不是精确片长。
- `stats` 是可重算的派生信息；验收入口会重新计算，不信任外部写入的值。

### 4. `report.json`（验收报告）

```json
{
  "schema_version": 1,
  "kind": "screenplay-adapter-report",
  "stage": "plan | screenplay",
  "status": "pass | warn | fail",
  "stats": {"…": "…"},
  "gates": [
    {"id": "P003", "status": "pass", "message": "all 24 sentences covered exactly once", "scenes": []}
  ]
}
```

- `status` 由门状态聚合：任意 `fail` → `fail`；否则任意 `warn` → `warn`；否则 `pass`。
- `stage` 表示这次报告是计划门还是剧本门；`assemble` 会先跑计划门和剧本门，只有 `pass`/`warn` 才写 `screenplay.json`/Fountain/Markdown；`fail` 时只写 `report.json` 并清掉旧的剧本产物。
- 门 id 稳定：`P001...` 计划，`S000...` 剧本；新增门只追加，不复用旧 id。

## 备选方案

- **只存 Fountain**：人读好，但来源区间、计划哈希、人物引用无法可靠解析；否决。
- **每个场一个 Markdown**：diff 友好，但机器校验和下游消费都要解析自然语言；否决。
- **把统计写进事实源并信任它**：容易出现“报告说通过但数据已变”；统计只做派生，验收重算。
- **草稿不记指纹**：实现简单，但改 brief/原文后旧草稿会静默混用；否决。
- **哈希包含 `warnings`**：warning 是提示，不是结构；包含会让无关提示使草稿失效，否决。

## 后果

- schema 是长期接口；字段改名/语义变化需要 `schema_version` 递增和迁移说明。
- `plan_hash` 让“改计划后旧草稿全部失效”成为显式行为；用户需要重跑受影响场次，不能用旧正文冒充新计划。
- `estimated_seconds` 只是启发式，报告必须用“估算/目标”而不是“片长”措辞。
- 下游（video-director 等）必须按自己的契约校验 `screenplay.json`，不能依赖本项目的内部类型。
- 场 id 只在同一个项目内稳定；改源文本后重新 `adapt` 会重建 id，旧草稿应拒绝。
