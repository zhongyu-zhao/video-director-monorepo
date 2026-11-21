"""Shot-boundary detector adapters and a motion-based router.

The ffmpeg scene score is cheap and works well on clear cuts, but it
also fires on large camera/subject motion.  The router keeps that fast
path for static/dialogue footage and escalates high-motion videos to a
more motion-robust detector.  Detector-specific thresholds are recorded
in ``detection.json``; the shot table only stores the selected name.

Heavy detectors are optional: ``auto`` never imports PyTorch unless the
``transnetv2`` path is explicitly selected (or ``prefer_neural`` is set).
"""

from __future__ import annotations

import importlib.util
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .detect import Cut, detect_cuts, scan_scores
from .models import MediaInfo, round_time
from .probe import probe

FFMPEG = "ffmpeg-scene"
PYSCENEDETECT = "pyscenedetect-adaptive"
TRANSNETV2 = "transnetv2"

_HIGH_MOTION_P95 = 0.05
_HIGH_MOTION_RATIO = 0.02
_HIGH_CUT_RATE = 15.0
_HIGH_MOTION_SCORE = 0.10


class DetectorUnavailable(RuntimeError):
    """Raised when an explicitly requested optional detector is missing."""


@dataclass(frozen=True)
class MotionProfile:
    frames: int
    duration: float
    mean_score: float
    p95_score: float
    high_motion_ratio: float
    candidate_rate: float
    threshold: float

    @property
    def high_motion(self) -> bool:
        return (
            self.p95_score >= _HIGH_MOTION_P95
            or self.high_motion_ratio >= _HIGH_MOTION_RATIO
            or (self.duration >= 60.0 and self.candidate_rate >= _HIGH_CUT_RATE)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "frames": self.frames,
            "duration": round(self.duration, 3),
            "mean_score": round(self.mean_score, 4),
            "p95_score": round(self.p95_score, 4),
            "high_motion_ratio": round(self.high_motion_ratio, 4),
            "candidate_rate": round(self.candidate_rate, 2),
            "threshold": self.threshold,
            "high_motion": self.high_motion,
        }

    def summary(self) -> str:
        return (
            f"p95={self.p95_score:.3f}, high_motion_ratio={self.high_motion_ratio:.3f}, "
            f"candidate_rate={self.candidate_rate:.1f}/min"
        )


@dataclass(frozen=True)
class DetectionResult:
    cuts: list[float]
    detector: str
    threshold: float
    requested: str
    route: str
    reason: str
    profile: MotionProfile | None
    latency_seconds: float
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "requested": self.requested,
            "selected": self.detector,
            "route": self.route,
            "reason": self.reason,
            "threshold": self.threshold,
            "latency_seconds": round(self.latency_seconds, 2),
            "cut_count": len(self.cuts),
            "profile": self.profile.to_dict() if self.profile else None,
            "notes": self.notes,
        }


class Detector(Protocol):
    name: str
    threshold: float

    def detect(self, path: str | Path) -> list[float]:
        """Return shot start times in seconds."""


class FfmpegDetector:
    name = FFMPEG

    def __init__(self, threshold: float = 0.25) -> None:
        self.threshold = threshold

    def detect(self, path: str | Path) -> list[float]:
        return [cut.time for cut in detect_cuts(path, threshold=self.threshold)]


class PySceneDetectDetector:
    """PySceneDetect's adaptive/content detectors, with flash filtering."""

    def __init__(self, method: str = "adaptive", min_scene_len: int = 15) -> None:
        if method not in {"adaptive", "content"}:
            raise ValueError("method must be 'adaptive' or 'content'")
        self.method = method
        self.min_scene_len = min_scene_len
        self.name = PYSCENEDETECT if method == "adaptive" else "pyscenedetect-content"
        self.threshold = 3.0 if method == "adaptive" else 27.0

    @staticmethod
    def available() -> bool:
        return importlib.util.find_spec("scenedetect") is not None and importlib.util.find_spec("cv2") is not None

    def detect(self, path: str | Path) -> list[float]:
        try:
            from scenedetect import AdaptiveDetector, ContentDetector, SceneManager, open_video
        except ImportError as error:
            raise DetectorUnavailable(
                "PySceneDetect is not installed; install the optional sbd extra "
                "(scenedetect + opencv-python-headless)"
            ) from error

        detector = (
            AdaptiveDetector(min_scene_len=self.min_scene_len)
            if self.method == "adaptive"
            else ContentDetector(min_scene_len=self.min_scene_len)
        )
        video = open_video(str(path))
        manager = SceneManager()
        manager.add_detector(detector)
        manager.detect_scenes(video, show_progress=False)
        scenes = manager.get_scene_list()
        cuts: list[float] = []
        for start, _end in scenes[1:]:
            seconds = getattr(start, "seconds", None)
            if seconds is None:
                seconds = start.get_seconds()
            cuts.append(round_time(float(seconds)))
        return cuts


class TransNetV2Detector:
    """TransNetV2 neural shot-boundary detector (optional, CPU by default)."""

    name = TRANSNETV2
    threshold = 0.5

    def __init__(self, threshold: float = 0.5, device: str = "cpu") -> None:
        self.threshold = threshold
        self.device = device

    @staticmethod
    def available() -> bool:
        return (
            importlib.util.find_spec("transnetv2_pytorch") is not None
            and importlib.util.find_spec("torch") is not None
        )

    def detect(self, path: str | Path) -> list[float]:
        try:
            from transnetv2_pytorch import TransNetV2
        except ImportError as error:
            raise DetectorUnavailable(
                "TransNetV2 is not installed; install the optional neural extra "
                "(transnetv2-pytorch + torch)"
            ) from error

        model = TransNetV2(device=self.device)
        scenes = model.detect_scenes(str(path), threshold=self.threshold)
        cuts: list[float] = []
        for scene in scenes[1:]:
            cuts.append(round_time(float(scene["start_time"])))
        return cuts


def profile_scores(
    path: str | Path,
    media: MediaInfo | None = None,
    threshold: float = 0.25,
) -> tuple[MotionProfile, list[float]]:
    """One ffmpeg pass: every scene score plus cuts at ``threshold``."""

    info = media or probe(path)
    samples: list[Cut] = scan_scores(path)
    scores = [cut.score if cut.score is not None else 0.0 for cut in samples]
    if not scores:
        return (
            MotionProfile(0, info.duration, 0.0, 0.0, 0.0, 0.0, threshold),
            [],
        )
    ordered = sorted(scores)
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    high_motion_ratio = sum(1 for score in scores if score >= _HIGH_MOTION_SCORE) / len(scores)
    candidates = [cut.time for cut in samples if (cut.score or 0.0) >= threshold]
    minutes = max(info.duration / 60.0, 1e-9)
    profile = MotionProfile(
        frames=len(scores),
        duration=info.duration,
        mean_score=sum(scores) / len(scores),
        p95_score=p95,
        high_motion_ratio=high_motion_ratio,
        candidate_rate=len(candidates) / minutes,
        threshold=threshold,
    )
    return profile, candidates


def detect_with_router(
    path: str | Path,
    media: MediaInfo | None = None,
    detector: str = "auto",
    threshold: float = 0.25,
    prefer_neural: bool = False,
) -> DetectionResult:
    requested = detector
    started = time.perf_counter()
    if detector not in {"auto", "ffmpeg", "pyscenedetect", "transnetv2"}:
        raise ValueError("detector must be auto, ffmpeg, pyscenedetect or transnetv2")
    if not 0.0 < threshold <= 1.0:
        raise ValueError("threshold must be in (0.0, 1.0]")

    if detector == "ffmpeg":
        cuts = FfmpegDetector(threshold).detect(path)
        return _result(cuts, FFMPEG, threshold, requested, "explicit", "explicit ffmpeg request", None, started)

    if detector == "pyscenedetect":
        chosen = PySceneDetectDetector()
        if not chosen.available():
            raise DetectorUnavailable(
                "PySceneDetect is not installed; install scenedetect and opencv-python-headless"
            )
        cuts = chosen.detect(path)
        return _result(
            cuts,
            chosen.name,
            chosen.threshold,
            requested,
            "explicit",
            "explicit PySceneDetect request",
            None,
            started,
        )

    if detector == "transnetv2":
        chosen = TransNetV2Detector()
        if not chosen.available():
            raise DetectorUnavailable(
                "TransNetV2 is not installed; install transnetv2-pytorch and torch"
            )
        cuts = chosen.detect(path)
        return _result(
            cuts,
            chosen.name,
            chosen.threshold,
            requested,
            "explicit",
            "explicit TransNetV2 request",
            None,
            started,
        )

    profile, baseline = profile_scores(path, media, threshold)
    if not profile.high_motion:
        return _result(
            baseline,
            FFMPEG,
            threshold,
            requested,
            "auto",
            f"low motion ({profile.summary()})",
            profile,
            started,
        )

    if prefer_neural and TransNetV2Detector.available():
        chosen = TransNetV2Detector()
        cuts = chosen.detect(path)
        return _result(
            cuts,
            chosen.name,
            chosen.threshold,
            requested,
            "auto",
            f"high motion ({profile.summary()}) and prefer_neural",
            profile,
            started,
        )

    if PySceneDetectDetector.available():
        chosen = PySceneDetectDetector()
        cuts = chosen.detect(path)
        return _result(
            cuts,
            chosen.name,
            chosen.threshold,
            requested,
            "auto",
            f"high motion ({profile.summary()}) -> PySceneDetect adaptive",
            profile,
            started,
        )

    if TransNetV2Detector.available():
        chosen = TransNetV2Detector()
        cuts = chosen.detect(path)
        return _result(
            cuts,
            chosen.name,
            chosen.threshold,
            requested,
            "auto",
            f"high motion ({profile.summary()}); PySceneDetect unavailable -> TransNetV2",
            profile,
            started,
        )

    return _result(
        baseline,
        FFMPEG,
        threshold,
        requested,
        "auto-fallback",
        f"high motion ({profile.summary()}) but no alternative detector is installed",
        profile,
        started,
        notes=["install the sbd extra for PySceneDetect or neural extra for TransNetV2"],
    )


def _result(
    cuts: list[float],
    detector_name: str,
    threshold: float,
    requested: str,
    route: str,
    reason: str,
    profile: MotionProfile | None,
    started: float,
    notes: list[str] | None = None,
) -> DetectionResult:
    return DetectionResult(
        cuts=cuts,
        detector=detector_name,
        threshold=threshold,
        requested=requested,
        route=route,
        reason=reason,
        profile=profile,
        latency_seconds=time.perf_counter() - started,
        notes=notes or [],
    )
