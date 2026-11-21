"""Render the M0 shot table as a human-readable Markdown report."""

from __future__ import annotations

from .detectors import DetectionResult
from .models import ShotTable
from .quality import FAIL, PASS, SKIP, QualityReport

_STATUS_LABELS = {PASS: "通过", FAIL: "失败", SKIP: "跳过"}


def format_timecode(seconds: float) -> str:
    total_milliseconds = round(float(seconds) * 1000)
    hours, remainder = divmod(total_milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{milliseconds:03d}"


def render_report(
    table: ShotTable,
    quality: QualityReport,
    detection: DetectionResult | None = None,
) -> str:
    shots = table.shots
    counts = quality.counts()
    mean_duration = sum(shot.duration for shot in shots) / len(shots) if shots else 0.0
    cuts_per_minute = 0.0
    if table.video.duration > 0 and len(shots) > 1:
        cuts_per_minute = (len(shots) - 1) / table.video.duration * 60.0

    lines = [
        "# 镜头表",
        "",
        f"- 输入：`{_escape(table.video.path)}`",
        f"- 时长：{format_timecode(table.video.duration)}（{table.video.duration:.3f}s）",
        f"- 画幅：{table.video.width}x{table.video.height} @ {table.video.fps:.3f}fps",
        f"- 镜头数：{len(shots)}",
        f"- 平均镜长：{mean_duration:.3f}s",
        f"- 剪辑频率：{cuts_per_minute:.1f} 次/分钟",
        f"- 检测器：{table.detector.name}（threshold={table.detector.threshold:.3f}）",
    ]
    if detection is not None:
        lines.extend(
            [
                f"- 路由：{detection.route}（{detection.reason}）",
                f"- 检测耗时：{detection.latency_seconds:.2f}s",
            ]
        )
    lines.extend(
        [
            "",
            (
                f"## 质量门：{'通过' if quality.ok else '未通过'}"
                f"（{counts[PASS]} 通过 / {counts[FAIL]} 失败 / {counts[SKIP]} 跳过）"
            ),
            "",
            "| 门 | 状态 | 说明 |",
            "|---|---|---|",
        ]
    )
    for check in quality.checks:
        lines.append(
            f"| `{check.id}` | {_STATUS_LABELS.get(check.status, check.status)} | "
            f"{_escape(check.detail)} |"
        )

    lines.extend(
        [
            "",
            "## 镜头表",
            "",
            "| 镜号 | 入点 | 出点 | 时长 | 转场 | 来源 |",
            "|---|---|---|---|---|---|",
        ]
    )
    if shots:
        for shot in shots:
            lines.append(
                f"| {shot.shot_id} | {format_timecode(shot.start)} | "
                f"{format_timecode(shot.end)} | {shot.duration:.3f}s | "
                f"{shot.transition_in} | {shot.source} |"
            )
    else:
        lines.append("| - | - | - | - | - | - |")

    lines.extend(
        [
            "",
            (
                "本报告只包含 M0 事实层（切点、时长、质量门）；逐镜视听语言分析、证据和置信度"
                "在后续里程碑加入，镜头表仍是唯一事实源。"
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _escape(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")
