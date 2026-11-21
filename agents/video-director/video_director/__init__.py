"""video-director: artifact-first video production kernel."""

from .project import create_project, load_project
from .render import render_project

__version__ = "0.1.0"
__all__ = ["__version__", "create_project", "load_project", "render_project"]
