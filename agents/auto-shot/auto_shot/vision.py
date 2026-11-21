"""Optional face measurement on keyframes.

OpenCV is an optional dependency.  Newer OpenCV releases no longer ship
``CascadeClassifier``; when a YuNet model path is supplied we use
``FaceDetectorYN``, otherwise we fall back to the Haar cascade when
available.  A missing model/detector returns ``None`` (skip), not 0.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

_DETECTORS: dict[tuple[str, int, int], Any] = {}
_CASCADE = None


def _haar():
    global _CASCADE
    if _CASCADE is None:
        import cv2

        if not hasattr(cv2, "CascadeClassifier"):
            raise ImportError("OpenCV has no CascadeClassifier")
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        if cascade.empty():
            raise ImportError("OpenCV haar cascade is unavailable")
        _CASCADE = cascade
    return _CASCADE


def _yunet(model_path: str, width: int, height: int):
    import cv2

    if not hasattr(cv2, "FaceDetectorYN_create"):
        raise ImportError("OpenCV has no FaceDetectorYN")
    key = (model_path, width, height)
    if key not in _DETECTORS:
        detector = cv2.FaceDetectorYN_create(model_path, "", (width, height), 0.6, 0.3, 5000)
        _DETECTORS[key] = detector
    return _DETECTORS[key]


def face_ratio(image_path: str | Path, model_path: str | Path | None = None) -> float | None:
    try:
        import cv2
    except ImportError:
        return None
    image = cv2.imread(str(image_path))
    if image is None:
        return None
    height, width = image.shape[:2]
    faces = []
    try:
        if model_path:
            detector = _yunet(str(model_path), width, height)
            detector.setInputSize((width, height))
            _retval, detected = detector.detect(image)
            faces = [] if detected is None else list(detected)
        else:
            cascade = _haar()
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            detected = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(20, 20))
            faces = list(detected)
    except Exception:  # noqa: BLE001 - optional detector must degrade, never crash evidence
        return None
    if len(faces) == 0:
        return 0.0
    largest = 0
    for face in faces:
        if len(face) >= 4:
            largest = max(largest, int(face[2]) * int(face[3]))
    return round(largest / float(width * height), 4)
