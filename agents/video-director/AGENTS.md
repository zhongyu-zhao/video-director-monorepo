# AGENTS.md — video-director 子 repo

本文件只写 video-director 子 repo 的规则；全局协作规则见 [`../../AGENTS.md`](../../AGENTS.md)。

## 命令

从 `agents/video-director/` 运行：

```bash
python3 -m unittest discover -v
python3 -m video_director init --root <dir> --title <title>
python3 -m video_director validate --root <dir>
python3 -m video_director render --root <dir>
```

依赖和入口以 `pyproject.toml` 为准。渲染集成测试在缺少 `ffmpeg`/`ffprobe` 时自动跳过。

## 结构

- `video_director/models.py`：Project / Asset / TimelineClip；字段变更先改契约决策记录。
- `video_director/project.py`：项目读写、revision 快照、素材复制、时间线追加。
- `video_director/validate.py`：渲染前必须通过的确定性检查。
- `video_director/render.py`：单轨 FFmpeg 渲染 + ffprobe 验收。
- `video_director/media.py`：外部工具边界。

## 规则

- 时间线是唯一事实源；预览、成片、报告都从 `project.json` 生成，不维护第二份数据。
- 项目修改必须走工具或显式保存：每次保存递增 `revision`，写 `history/project-r<NNN>.json`，不手改当前快照绕过版本。
- LLM 不能直接改 `project.json`；它只能通过工具追加/裁剪/移动片段，工具返回改动结果。
- `asset.path` 必须是项目内相对路径；解析后不能逃出项目根目录。
- 渲染前必须先通过 `validate`；`fail` 阻止渲染，`skip` 不算通过。
- 渲染必须可复现：固定 fps/分辨率/编码参数，渲染后用 ffprobe 验证时长、分辨率、fps。
- schema 变更必须加 `schema_version`、更新契约 ADR，并说明迁移方式。
- 不 import `auto-shot` 的代码；跨 agent 只交换版本化 JSON。
- 不提交视频、音频、图片等大资产；测试用 ffmpeg 现场生成合成素材。

## 相关文档

- [`README.md`](README.md)
- [`docs/architecture.md`](docs/architecture.md)
- [`docs/decisions/`](docs/decisions/)
