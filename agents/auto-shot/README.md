# auto-shot

自动拉片子 repo：输入一部片，输出可核对、可编辑的镜头表，并在镜头事实之上做逐镜视听语言分析。

当前处于 **M0（镜头表内核）**：切分镜头、生成镜头表、跑质量门、出 Markdown 镜头表。逐镜 VLM 标注、场景聚合、交互报告和人工 recut 还没有实现，路线图见 [`docs/architecture.md`](docs/architecture.md)。

## 要求

- Python 3.12+
- `ffmpeg` / `ffprobe` 6.x（M0 用 ffmpeg 场景检测作为基线切分器）

## 快速开始

```bash
cd agents/auto-shot
python3 -m auto_shot analyze /path/to/film.mp4 --out /tmp/film-shots
```

输出：

```text
/tmp/film-shots/
  shots.json     # 镜头表，唯一事实源
  quality.json   # 质量门结果
  report.md      # 镜头表报告
```

`analyze` 的参数：

```bash
python3 -m auto_shot analyze INPUT --out DIR [--threshold 0.3]
```

退出码：`0` 成功且质量门通过；`1` 产物已写出但质量门失败；`2` 输入或 ffmpeg 错误。

## 测试

```bash
cd agents/auto-shot
python3 -m unittest discover -v
```

集成测试会用 ffmpeg 生成 6 秒的黑/白/红硬切测试片；缺少 ffmpeg 时自动跳过，其余测试仍然运行。

## M0 的边界

- 切分器是 ffmpeg 的帧差场景分数，不是最终方案：它漏渐变、叠化和低亮度差的颜色切换，伪切点也没有专门处理。M1 会接 PySceneDetect / TransNetV2 / OmniShotCut 这类可替换检测器。
- 还没有 VLM 标注：`shots.json` 里只有测量事实，没有 `labels` / `evidence` / `confidence`。
- 没有 ASR、OCR、人脸、音频事件；这些属于 M1 证据层。
- 没有人工 recut UI；`manual_cuts` 字段已经预留，但 M0 不写。
- 没有 HTML/播放器联动；报告是静态 Markdown。

## 目录

```text
auto_shot/
  cli.py       # 命令行入口
  pipeline.py  # M0 编排：probe -> detect -> table -> gates -> report
  probe.py     # ffprobe 读取媒体事实
  detect.py    # ffmpeg 场景检测
  models.py    # 镜头表数据结构与 JSON 读写
  quality.py   # 质量门
  report.py    # Markdown 报告
tests/         # 单元测试 + 合成视频集成测试
docs/          # 架构、词表、决策记录
```

## 文档

- 架构与路线图：[`docs/architecture.md`](docs/architecture.md)
- 镜头表契约：[`docs/decisions/proposed/architecture/2026-11-21-shot-table-contract.md`](docs/decisions/proposed/architecture/2026-11-21-shot-table-contract.md)
- 四层流水线决策：[`docs/decisions/proposed/architecture/2026-11-21-auto-shot-pipeline.md`](docs/decisions/proposed/architecture/2026-11-21-auto-shot-pipeline.md)
- 词表草案：[`docs/taxonomy.md`](docs/taxonomy.md)

## 与其他子 repo 的边界

auto-shot 不 import `video-director` 的代码。需要把镜头表交给下游时，只通过版本化 JSON 文件；消费方自己校验，不共享内部模型。仓库级约定见 [`../../AGENTS.md`](../../AGENTS.md)。
