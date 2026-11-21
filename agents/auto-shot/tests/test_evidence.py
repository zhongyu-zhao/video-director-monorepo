from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from auto_shot.evidence import _aggregate, build_evidence
from auto_shot.models import ShotTable, shots_from_cuts
from auto_shot.probe import probe
from tests.support import ffmpeg_available, make_color_video, sample_table


@unittest.skipUnless(ffmpeg_available(), "ffmpeg required")
class EvidenceIntegrationTest(unittest.TestCase):
    def test_builds_proxy_bars_keyframes_and_measurements(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = make_color_video(root / "colors.mp4", ("black", "white", "red"), seconds=2.0)
            framed = root / "bars.mp4"
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(source),
                    "-vf",
                    "pad=480:240:80:0:black",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "ultrafast",
                    str(framed),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            media = probe(framed)
            table = ShotTable(
                video=media,
                detector=sample_table().detector,
                shots=shots_from_cuts([2.0, 4.0], media.duration),
            )
            result = build_evidence(table, framed, root / "evidence", keyframes=3)
            payload = json.loads(result.evidence_path.read_text(encoding="utf-8"))
            self.assertTrue((result.output_dir / "proxy-480.mp4").is_file())

        self.assertEqual(payload["black_bars"]["left"], 80)
        self.assertEqual(payload["black_bars"]["right"], 80)
        self.assertEqual(len(payload["shots"]), 3)
        first = payload["shots"]["S001"]
        self.assertEqual(first["contact_sheet"], "contact-sheets/S001.jpg")
        self.assertEqual(len(first["keyframes"]), 3)
        self.assertIn("brightness", first["measured"])
        self.assertGreater(first["measured"]["brightness"], 0.0)

    def test_audio_events_are_mapped_to_shots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "tone.mp4"
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=black:s=320x240:d=2:r=25",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:duration=2",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "ultrafast",
                    "-c:a",
                    "aac",
                    "-shortest",
                    str(source),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            media = probe(source)
            table = ShotTable(
                video=media,
                detector=sample_table().detector,
                shots=shots_from_cuts([1.0], media.duration),
            )
            result = build_evidence(table, source, root / "evidence", keyframes=3)

        self.assertTrue(table.video.has_audio)
        self.assertEqual(result.shots["S001"]["audio"]["silence_ratio"], 0.0)


class SignalAggregationTest(unittest.TestCase):
    def test_aggregates_frames_by_shot(self) -> None:
        table = sample_table()
        table.shots = shots_from_cuts([2.0], 6.0)
        frames = [
            {"time": 0.1, "YAVG": 100, "YHIGH": 150, "YLOW": 50, "SATAVG": 20, "HUEAVG": 100, "YDIF": 10},
            {"time": 1.9, "YAVG": 120, "YHIGH": 160, "YLOW": 60, "SATAVG": 30, "HUEAVG": 120, "YDIF": 20},
            {"time": 2.1, "YAVG": 80, "YHIGH": 130, "YLOW": 40, "SATAVG": 10, "HUEAVG": 80, "YDIF": 30},
        ]
        result = _aggregate(table, frames)
        self.assertAlmostEqual(result["S001"]["brightness"], 220 / 2 / 255, places=3)
        self.assertIn("S002", result)
        self.assertNotIn("S003", result)
