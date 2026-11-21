"""Milestone 0 pipeline: probe -> route/detect -> shot table -> gates -> report."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .detectors import DetectionResult, detect_with_router
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
    detection_path: Path
    table: ShotTable
    quality: QualityReport
    detection: DetectionResult


def analyze(
    input_path: str | Path,
    output_dir: str | Path,
    threshold: float = 0.25,
    detector: str = "auto",
    prefer_neural: bool = False,
) -> AnalysisResult:
    media = probe(input_path)
    detection = detect_with_router(
        input_path,
        media=media,
        detector=detector,
        threshold=threshold,
        prefer_neural=prefer_neural,
    )
    table = ShotTable(
        video=media,
        detector=DetectorInfo(name=detection.detector, threshold=detection.threshold),
        shots=shots_from_cuts(detection.cuts, media.duration),
    )
    quality = validate_shot_table(table)

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    shots_path = destination / "shots.json"
    quality_path = destination / "quality.json"
    report_path = destination / "report.md"
    detection_path = destination / "detection.json"

    table.save(shots_path)
    _write_json(quality_path, quality.to_dict())
    _write_json(detection_path, detection.to_dict())
    report_path.write_text(render_report(table, quality, detection), encoding="utf-8")

    return AnalysisResult(
        output_dir=destination,
        shots_path=shots_path,
        quality_path=quality_path,
        report_path=report_path,
        detection_path=detection_path,
        table=table,
        quality=quality,
        detection=detection,
    )


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
