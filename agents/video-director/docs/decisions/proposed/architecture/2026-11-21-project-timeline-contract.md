# 决策：Project / Timeline 工件契约

状态：proposed

## 问题

video-director 的“唯一事实源”需要落在具体文件上：哪些文件组成一个项目，时间线如何表达，人工和工具修改如何留下版本，渲染产物如何和某个版本对应。契约不稳定，后续的规划、生成、质检和 UI 都会反复迁移。

## 决定

### 项目目录

```text
project/
  project.json          # 当前事实源
  artifacts/            # 分阶段工件（提案/剧本/分镜/资产清单/剪辑决策）
  assets/               # 本地素材（视频/图片/音频），不进 git
  renders/              # 中间渲染与成片
  history/              # 每次 revision 的快照，不丢审批轨迹
```

### project.json

```json
{
  "schema_version": 1,
  "project_id": "proj-01",
  "title": "demo",
  "status": "draft",
  "revision": 1,
  "fps": 25.0,
  "width": 320,
  "height": 180,
  "assets": [
    {
      "id": "A001",
      "path": "assets/a.mp4",
      "kind": "video",
      "duration": 2.0
    }
  ],
  "timeline": {
    "clips": [
      {
        "id": "C001",
        "asset_id": "A001",
        "start": 0.0,
        "source_in": 0.0,
        "source_out": 2.0
      }
    ]
  }
}
```

- `schema_version` 是整数；破坏性变更加一，并附 migration。
- `asset.path` 是相对项目根目录的路径，项目可以整体搬移；路径解析后必须仍在项目根目录内。外部素材引用留给后续版本，用 hash + 来源记录解决。
- `duration = source_out - source_in`；`start` 是时间线上的绝对位置。时间统一用秒，保留 3 位小数。
- 时间线在首个纵切里只有一个视频轨：从 0 开始、无空隙、无重叠。多轨、转场、音频、字幕在后续 schema 版本加入。
- `status` 只表达项目阶段（`draft` / `approved` 等），不表达渲染是否成功；渲染结果在 `render_report.json`。

### 版本与渲染

- `revision` 从 1 开始，每次通过工具或人工保存都加一；`history/project-r<NNN>.json` 保存该 revision 的完整快照。
- 写入先写临时文件再原子替换，避免半写状态。
- `render` 只读当前 `project.json`，输出 `renders/render-r<NNN>.mp4` 和 `renders/render_report.json`；报告记录 `project_revision`、输入片段数、期望/实际时长、分辨率、帧率和检查结果。
- 渲染前必须通过校验（schema、id、路径、in/out、时间线连续）；任何 `fail` 都阻止渲染，`skip` 不算通过。

## 备选方案

- **绝对路径引用素材**：实现简单，但项目不可搬移、无法复现，否决。
- **把最终 MP4 当状态**：无法编辑和增量重渲，否决。
- **数据库存项目**：查询和事务更强，但 diff、review 和版本对比差；MVP 用 JSON，等查询成为瓶颈再加索引。
- **一上来就多轨/转场/音频**：schema 复杂度高，首个纵切无法验证；先用单轨把“可校验、可渲染、可版本化”跑通。

## 后果

- JSON + 版本快照会让大项目产生较多文件；换来可读、可 diff、可回滚。
- 相对路径约束要求素材放进项目目录；这对真实工作流偏严，后续需要“外部素材引用”设计。
- 单轨 MVP 不能表达转场/叠加；这是有意的范围控制，schema 已预留版本化扩展。
