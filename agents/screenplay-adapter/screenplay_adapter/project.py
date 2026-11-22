"""Project directory IO for screenplay-adapter.

A project is a directory with a fixed layout:

```text
project/
  source/source.md   # normalized copy of the input, local only
  adaptation.json    # the plan (source of truth)
  briefs.md          # per-scene writing briefs
  drafts/S001.json   # one draft per scene
  screenplay.json    # merged drafts + plan references
  screenplay.fountain
  screenplay.md
  report.json        # latest deterministic gates
```

The source copy makes the project self-contained; drafts and plans reference
its hash, so editing the source invalidates old drafts instead of silently
mixing versions.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .models import AdaptationPlan, AdapterError, SceneDraft, Screenplay
from .source import parse_source

SOURCE_RELATIVE_PATH = "source/source.md"
PLAN_FILENAME = "adaptation.json"
BRIEFS_FILENAME = "briefs.md"
SCREENPLAY_FILENAME = "screenplay.json"
FOUNTAIN_FILENAME = "screenplay.fountain"
MARKDOWN_FILENAME = "screenplay.md"
REPORT_FILENAME = "report.json"
DRAFTS_DIR = "drafts"


def ensure_root(root: Path) -> Path:
    root = Path(root)
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise AdapterError(f"cannot create project directory {root}: {error}") from error
    return root


def write_source(root: Path, text: str) -> Path:
    path = ensure_root(root) / SOURCE_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_text(path, text)
    return path


def load_source(root: Path):
    path = Path(root) / SOURCE_RELATIVE_PATH
    if not path.is_file():
        raise AdapterError(f"missing source copy: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise AdapterError(f"cannot read source copy {path}: {error}") from error
    return parse_source(text, path=SOURCE_RELATIVE_PATH)


def save_plan(root: Path, plan: AdaptationPlan) -> Path:
    return write_json(Path(root) / PLAN_FILENAME, plan.to_dict())


def load_plan(root: Path) -> AdaptationPlan:
    path = Path(root) / PLAN_FILENAME
    data = read_json(path, "adaptation plan")
    try:
        return AdaptationPlan.from_dict(data)
    except (KeyError, TypeError, ValueError) as error:
        raise AdapterError(f"invalid adaptation plan {path}: {error}") from error


def save_briefs(root: Path, markdown: str) -> Path:
    path = ensure_root(root) / BRIEFS_FILENAME
    _write_text(path, markdown)
    return path


def save_draft(root: Path, draft: SceneDraft) -> Path:
    path = ensure_root(root) / DRAFTS_DIR / f"{draft.scene_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return write_json(path, draft.to_dict())


def load_drafts(root: Path) -> dict[str, SceneDraft]:
    directory = Path(root) / DRAFTS_DIR
    if not directory.is_dir():
        return {}
    drafts: dict[str, SceneDraft] = {}
    for path in sorted(directory.glob("*.json")):
        data = read_json(path, f"draft {path.name}")
        try:
            draft = SceneDraft.from_dict(data)
        except (KeyError, TypeError, ValueError) as error:
            raise AdapterError(f"invalid draft {path}: {error}") from error
        if draft.scene_id in drafts:
            raise AdapterError(f"duplicate draft for scene {draft.scene_id}")
        drafts[draft.scene_id] = draft
    return drafts


def save_screenplay(root: Path, screenplay: Screenplay) -> Path:
    return write_json(Path(root) / SCREENPLAY_FILENAME, screenplay.to_dict())


def load_screenplay(root: Path) -> Screenplay | None:
    path = Path(root) / SCREENPLAY_FILENAME
    if not path.is_file():
        return None
    data = read_json(path, "screenplay")
    try:
        return Screenplay.from_dict(data)
    except (KeyError, TypeError, ValueError) as error:
        raise AdapterError(f"invalid screenplay {path}: {error}") from error


def save_report(root: Path, report: dict[str, Any]) -> Path:
    return write_json(Path(root) / REPORT_FILENAME, report)


def write_exports(root: Path, fountain: str, markdown: str) -> tuple[Path, Path]:
    root = ensure_root(root)
    fountain_path = root / FOUNTAIN_FILENAME
    markdown_path = root / MARKDOWN_FILENAME
    _write_text(fountain_path, fountain)
    _write_text(markdown_path, markdown)
    return fountain_path, markdown_path


def write_json(path: Path, payload: Any) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    temporary = path.with_name(path.name + ".tmp")
    _write_text(temporary, text)
    try:
        os.replace(temporary, path)
    except OSError as error:
        raise AdapterError(f"cannot write {path}: {error}") from error
    return path


def read_json(path: Path, what: str) -> Any:
    path = Path(path)
    if not path.is_file():
        raise AdapterError(f"missing {what}: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise AdapterError(f"cannot read {what} {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise AdapterError(f"{what} {path} is not valid JSON: {error}") from error


def read_env_file(path: Path) -> dict[str, str]:
    """Read KEY=VALUE pairs without echoing values anywhere."""

    if not Path(path).is_file():
        raise AdapterError(f"env file not found: {path}")
    values: dict[str, str] = {}
    for line_number, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            raise AdapterError(f"invalid env line {line_number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value[:1] == value[-1:] and value[:1] in ("'", '"') and len(value) >= 2:
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def _write_text(path: Path, text: str) -> None:
    try:
        path.write_text(text, encoding="utf-8")
    except OSError as error:
        raise AdapterError(f"cannot write {path}: {error}") from error
