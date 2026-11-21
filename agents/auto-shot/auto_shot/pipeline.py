"""Milestone 0 pipeline: probe -> detect -> shot table -> gates -> report."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .detect import detect_cuts
from .models import DetectorInfo, ShotTable, shots_from_cuts
from .probe import probe
from .quality import QualityReport, validate_shot_table
from .report import render_report


@dataclass(frozen=True)
class AnalysisResult:
    output_dir: Path
    shots_path: Path
    quality_path: Path
    report_path: Path
    table: ShotTable
    quality: QualityReport


def analyze(input_path: str | Path, output_dir: str | Path, threshold: float = 0.3) -> AnalysisResult:
    media = probe(input_path)
    cuts = detect_cuts(input_path, threshold=threshold)
    table = ShotTable(
        video=media,
        detector=DetectorInfo(name="ffmpeg-scene", threshold=threshold),
        shots=shots_from_cuts([cut.time for cut in cuts], media.duration),
    )
    quality = validate_shot_table(table)

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    shots_path = destination / "shots.json"
    quality_path = destination / "quality.json"
    report_path = destination / "report.md"

    table.save(shots_path)
    _write_json(quality_path, quality.to_dict())
    report_path.write_text(render_report(table, quality), encoding="utf-8")

    return AnalysisResult(
        output_dir=destination,
        shots_path=shots_path,
        quality_path=quality_path,
        report_path=report_path,
        table=table,
        quality=quality,
    )


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
