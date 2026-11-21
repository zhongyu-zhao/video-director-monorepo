from __future__ import annotations

import unittest
from unittest import mock

from auto_shot import detectors
from auto_shot.detectors import (
    FFMPEG,
    PYSCENEDETECT,
    TRANSNETV2,
    DetectorUnavailable,
    MotionProfile,
    PySceneDetectDetector,
    TransNetV2Detector,
    detect_with_router,
)


def profile(*, p95: float = 0.01, ratio: float = 0.0, rate: float = 2.0, duration: float = 120.0) -> MotionProfile:
    return MotionProfile(
        frames=3000,
        duration=duration,
        mean_score=p95 / 4,
        p95_score=p95,
        high_motion_ratio=ratio,
        candidate_rate=rate,
        threshold=0.25,
    )


class MotionProfileTest(unittest.TestCase):
    def test_low_motion(self) -> None:
        self.assertFalse(profile(p95=0.01, ratio=0.001, rate=2).high_motion)

    def test_high_p95_routes_to_high_motion(self) -> None:
        self.assertTrue(profile(p95=0.08).high_motion)

    def test_high_motion_ratio_routes_to_high_motion(self) -> None:
        self.assertTrue(profile(p95=0.01, ratio=0.03).high_motion)

    def test_short_clip_cut_rate_does_not_fake_high_motion(self) -> None:
        self.assertFalse(profile(p95=0.01, ratio=0.01, rate=40, duration=6).high_motion)


class RouterTest(unittest.TestCase):
    def test_explicit_detector_skips_profile(self) -> None:
        with mock.patch.object(detectors.FfmpegDetector, "detect", return_value=[1.0, 2.0]) as detect:
            result = detect_with_router("input.mp4", detector="ffmpeg", threshold=0.25)

        self.assertEqual(result.cuts, [1.0, 2.0])
        self.assertEqual((result.detector, result.route), (FFMPEG, "explicit"))
        self.assertIsNone(result.profile)
        detect.assert_called_once()

    def test_low_motion_uses_ffmpeg_baseline(self) -> None:
        with mock.patch.object(detectors, "profile_scores", return_value=(profile(), [1.0, 2.0])):
            result = detect_with_router("input.mp4", detector="auto")

        self.assertEqual(result.cuts, [1.0, 2.0])
        self.assertEqual((result.detector, result.route), (FFMPEG, "auto"))

    def test_high_motion_routes_to_pyscenedetect(self) -> None:
        with (
            mock.patch.object(detectors, "profile_scores", return_value=(profile(p95=0.2), [1.0])),
            mock.patch.object(PySceneDetectDetector, "available", return_value=True),
            mock.patch.object(PySceneDetectDetector, "detect", return_value=[1.5, 3.5]),
        ):
            result = detect_with_router("input.mp4", detector="auto")

        self.assertEqual(result.cuts, [1.5, 3.5])
        self.assertEqual(result.detector, PYSCENEDETECT)
        self.assertIn("PySceneDetect", result.reason)

    def test_prefer_neural_uses_transnetv2(self) -> None:
        with (
            mock.patch.object(detectors, "profile_scores", return_value=(profile(p95=0.2), [1.0])),
            mock.patch.object(TransNetV2Detector, "available", return_value=True),
            mock.patch.object(TransNetV2Detector, "detect", return_value=[2.0, 4.0]),
        ):
            result = detect_with_router("input.mp4", detector="auto", prefer_neural=True)

        self.assertEqual(result.cuts, [2.0, 4.0])
        self.assertEqual(result.detector, TRANSNETV2)

    def test_high_motion_without_extras_falls_back(self) -> None:
        with (
            mock.patch.object(detectors, "profile_scores", return_value=(profile(p95=0.2), [1.0])),
            mock.patch.object(PySceneDetectDetector, "available", return_value=False),
            mock.patch.object(TransNetV2Detector, "available", return_value=False),
        ):
            result = detect_with_router("input.mp4", detector="auto")

        self.assertEqual(result.cuts, [1.0])
        self.assertEqual(result.detector, FFMPEG)
        self.assertEqual(result.route, "auto-fallback")
        self.assertTrue(result.notes)

    def test_explicit_missing_detector_is_actionable(self) -> None:
        with (
            mock.patch.object(PySceneDetectDetector, "available", return_value=False),
            self.assertRaises(DetectorUnavailable) as context,
        ):
            detect_with_router("input.mp4", detector="pyscenedetect")

        self.assertIn("PySceneDetect", str(context.exception))


if __name__ == "__main__":
    unittest.main()
