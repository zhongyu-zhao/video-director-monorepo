"""Vocabulary for model-produced shot labels.

The values mirror ``docs/taxonomy.md``.  Keeping them in code lets the
labeler reject hallucinated enum values before they reach the shot
table; the docs remain the human-readable criteria.
"""

from __future__ import annotations

from typing import Any

SCALES = (
    "extreme-long",
    "long",
    "full",
    "medium",
    "medium-close",
    "close",
    "extreme-close",
    "foreground",
    "insert",
    "unknown",
)
ANGLES = (
    "eye-level",
    "high-angle",
    "low-angle",
    "birds-eye",
    "dutch",
    "over-the-shoulder",
    "point-of-view",
    "unknown",
)
CAMERAS = (
    "static",
    "pan",
    "tilt",
    "push-in",
    "pull-out",
    "track",
    "crane-up",
    "crane-down",
    "handheld",
    "orbit",
    "zoom-in",
    "zoom-out",
    "rack-focus",
    "drone",
    "unknown",
)
COMPOSITIONS = (
    "rule-of-thirds",
    "centered",
    "symmetrical",
    "frame-within-frame",
    "foreground-occlusion",
    "negative-space",
    "lead-room",
    "unknown",
)
LIGHTING = (
    "high-key",
    "low-key",
    "hard",
    "soft",
    "backlight",
    "side-light",
    "top-light",
    "under-light",
    "practical",
    "natural",
    "unknown",
)
COLORS = (
    "warm",
    "cool",
    "saturated",
    "desaturated",
    "monochrome",
    "complementary",
    "unknown",
)
DOF = ("shallow", "deep", "unknown")

LABEL_FIELDS: dict[str, tuple[str, ...]] = {
    "scale": SCALES,
    "angle": ANGLES,
    "camera": CAMERAS,
    "composition": COMPOSITIONS,
    "lighting": LIGHTING,
    "color": COLORS,
    "dof": DOF,
}


def validate_label_values(labels: dict[str, Any]) -> list[str]:
    """Return actionable errors for invalid or missing label values."""

    errors: list[str] = []
    for field, allowed in LABEL_FIELDS.items():
        if field not in labels:
            errors.append(f"missing label '{field}'")
            continue
        value = labels[field]
        if value not in allowed:
            errors.append(f"'{field}' has value {value!r}; allowed: {', '.join(allowed)}")
    return errors
