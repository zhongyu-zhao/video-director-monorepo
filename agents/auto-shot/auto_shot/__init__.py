"""auto-shot: deterministic shot tables plus model judgments, kept separate."""

from .label import label_shots
from .pipeline import analyze
from .review import apply_review, render_review_html
from .verify import verify_short_shots

__version__ = "0.1.0"
__all__ = [
    "__version__",
    "analyze",
    "apply_review",
    "label_shots",
    "render_review_html",
    "verify_short_shots",
]
