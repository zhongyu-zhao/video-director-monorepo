"""Generate a local cut-review page and apply human corrections.

The page is a single HTML file: a video player, the shot list, and
buttons to flag false cuts or mark missed cuts.  It exports a small JSON
file; ``apply_review`` turns that file back into a new shot table with
manual boundaries recorded, without touching the original artifact.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .models import MIN_SHOT_SECONDS, Shot, ShotTable, round_time
from .quality import validate_shot_table


class ReviewError(RuntimeError):
    """Raised when a review flag file cannot be applied safely."""


def render_review_html(
    table: ShotTable,
    video: str | Path,
    output: str | Path,
    status: str = "自动检测",
    labels: dict[str, Any] | None = None,
    scenes: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
    source_table: ShotTable | None = None,
    evidence_dir: str | Path | None = None,
) -> Path:
    """Write a self-contained review page and return its path.

    ``status`` is shown in the header so a page cannot silently look
    current while representing an older detection/verification stage.
    """

    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)

    video_path = Path(video).resolve()
    relative = Path(os.path.relpath(video_path, destination.parent.resolve())).as_posix()
    video_src = quote(relative, safe="/.")
    shots_json = json.dumps(
        [shot.to_dict() for shot in table.shots],
        ensure_ascii=False,
    ).replace("</", "<\\/")

    annotations, scene_cards = build_review_annotations(
        table,
        labels=labels,
        scenes=scenes,
        evidence=evidence,
        source_table=source_table,
        evidence_dir=evidence_dir,
        output_dir=destination.parent,
    )
    annotations_json = json.dumps(annotations, ensure_ascii=False).replace("</", "<\\/")
    scenes_json = json.dumps(scene_cards, ensure_ascii=False).replace("</", "<\\/")
    page = _TEMPLATE.replace("__SHOTS_JSON__", shots_json)
    page = page.replace("__ANNOTATIONS_JSON__", annotations_json)
    page = page.replace("__SCENES_JSON__", scenes_json)
    page = page.replace("__LABEL_COUNT__", str(sum(1 for item in annotations.values() if item["label"])))
    page = page.replace("__SCENE_COUNT__", str(len(scene_cards)))
    page = page.replace("__VIDEO_SRC__", html.escape(video_src))
    page = page.replace("__SOURCE_JSON__", json.dumps(table.video.path, ensure_ascii=False).replace("</", "<\\/"))
    signature = "|".join(
        f"{shot.start:.3f}:{shot.end:.3f}:{shot.transition_in}" for shot in table.shots
    )
    review_key = (
        f"{table.video.path}|{table.detector.name}:{table.detector.threshold:.3f}|"
        f"{hashlib.sha1(signature.encode()).hexdigest()[:16]}"
    )
    page = page.replace("__REVIEW_KEY_JSON__", json.dumps(review_key, ensure_ascii=False).replace("</", "<\\/"))
    page = page.replace("__SOURCE__", html.escape(table.video.path))
    page = page.replace("__COUNT__", str(len(table.shots)))
    page = page.replace("__DURATION__", f"{table.video.duration:.3f}")
    page = page.replace("__DETECTOR__", html.escape(table.detector.name))
    page = page.replace("__THRESHOLD__", f"{table.detector.threshold:.3f}")
    page = page.replace("__STATUS__", html.escape(status))
    page = page.replace("__GENERATED__", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    destination.write_text(page, encoding="utf-8")
    return destination


def build_review_annotations(
    table: ShotTable,
    labels: dict[str, Any] | None = None,
    scenes: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
    source_table: ShotTable | None = None,
    evidence_dir: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Map labels/scenes/evidence onto the displayed shot table.

    Verified tables are renumbered, so annotations are matched by exact id
    first and then by the longest source-shot overlap.  The selected source
    shot is recorded so the UI can show which label/evidence was inherited.
    """

    labels_by = labels.get("shots", {}) if labels else {}
    evidence_by = evidence.get("shots", {}) if evidence else {}
    scene_list = scenes.get("scenes", []) if scenes else []
    source_shots = source_table.shots if source_table else []
    root = Path(output_dir).resolve() if output_dir else None
    evidence_root = Path(evidence_dir).resolve() if evidence_dir else None

    annotations: dict[str, dict[str, Any]] = {}
    for shot in table.shots:
        label = labels_by.get(shot.shot_id)
        primary_id = shot.shot_id
        merged_from: list[str] = []
        if label is None and source_shots:
            overlaps = [
                source
                for source in source_shots
                if min(source.end, shot.end) - max(source.start, shot.start) > 0
            ]
            if overlaps:
                primary = max(
                    overlaps,
                    key=lambda source: min(source.end, shot.end) - max(source.start, shot.start),
                )
                primary_id = primary.shot_id
                label = labels_by.get(primary_id)
                merged_from = [source.shot_id for source in overlaps if source.shot_id != primary_id]
        entry = evidence_by.get(shot.shot_id) or evidence_by.get(primary_id)
        scene, scene_overlap = _scene_for(shot, scene_list)
        annotations[shot.shot_id] = {
            "label": label,
            "label_source": primary_id if label is not None else None,
            "merged_from": merged_from,
            "scene_id": scene["scene_id"] if scene else None,
            "scene_title": _scene_title(scene) if scene else None,
            "scene_summary": _scene_summary(scene) if scene else None,
            "scene_overlap": round(scene_overlap, 3),
            "evidence": _evidence_view(entry, evidence_root, root),
        }

    scene_cards = []
    for scene in scene_list:
        scene_cards.append(
            {
                "scene_id": scene["scene_id"],
                "title": _scene_title(scene),
                "summary": _scene_summary(scene),
            }
        )
    return annotations, scene_cards


def _scene_for(shot: Shot, scenes: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, float]:
    best = None
    best_overlap = 0.0
    for scene in scenes:
        overlap = min(shot.end, float(scene["end"])) - max(shot.start, float(scene["start"]))
        if overlap > best_overlap:
            best = scene
            best_overlap = overlap
    return best, max(0.0, best_overlap)


def _scene_title(scene: dict[str, Any] | None) -> str:
    if not scene:
        return ""
    return (
        f"{scene['scene_id']} · {_timecode(float(scene['start']))}–{_timecode(float(scene['end']))} · "
        f"{scene.get('stats', {}).get('shot_count', len(scene.get('shot_ids', [])))} 镜"
    )


def _scene_summary(scene: dict[str, Any] | None) -> str:
    if not scene:
        return ""
    stats = scene.get("stats", {})
    parts = []
    for field, label in (("scale", "景别"), ("camera", "运镜"), ("lighting", "光线"), ("color", "色彩")):
        counts = stats.get(field, {})
        if counts:
            top = "、".join(f"{key} {value}" for key, value in list(counts.items())[:3])
            parts.append(f"{label} {top}")
    measured = []
    for field, label in (("brightness", "亮度"), ("motion", "运动"), ("face_ratio", "人脸")):
        value = stats.get(field)
        if isinstance(value, (int, float)):
            measured.append(f"{label} {value:.2f}")
    if measured:
        parts.append(" / ".join(measured))
    return " · ".join(parts)


def _evidence_view(
    entry: dict[str, Any] | None,
    evidence_root: Path | None,
    output_root: Path | None,
) -> dict[str, Any] | None:
    if not entry:
        return None
    view = {
        "measured": entry.get("measured", {}),
        "audio": entry.get("audio", {}),
        "contact_href": None,
        "keyframe_hrefs": [],
        "asr": entry.get("asr"),
    }
    if evidence_root and output_root:
        contact = entry.get("contact_sheet")
        if contact:
            view["contact_href"] = _relative(evidence_root / contact, output_root)
        view["keyframe_hrefs"] = [
            _relative(evidence_root / keyframe, output_root)
            for keyframe in entry.get("keyframes", [])
        ]
    return view


def _relative(target: Path, output_root: Path) -> str:
    return Path(os.path.relpath(target, output_root)).as_posix()


def _timecode(seconds: float) -> str:
    total = max(0, round(seconds))
    minutes, sec = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{sec:02d}" if hours else f"{minutes:02d}:{sec:02d}"


def apply_review(table: ShotTable, flags: dict[str, Any]) -> ShotTable:
    """Apply ``falseCuts`` / ``missedCuts`` from a review export.

    False cuts merge a shot into its predecessor.  Missed cuts split the
    containing shot.  The result is renumbered, marked as ``manual`` where
    a human changed a boundary, and validated with the normal gates.
    """

    if not isinstance(flags, dict):
        raise ReviewError("review flags must be a JSON object")
    false_ids = _false_cut_ids(flags)
    missed = _missed_cut_times(flags)

    working: list[dict[str, Any]] = []
    removed_boundaries: list[float] = []
    for shot in table.shots:
        if shot.shot_id not in false_ids:
            working.append(shot.to_dict())
            continue
        if not working:
            raise ReviewError(
                f"cannot merge {shot.shot_id}: it is the first shot and has no predecessor"
            )
        previous = working[-1]
        previous["end"] = shot.end
        previous["source"] = "manual"
        removed_boundaries.append(shot.start)

    applied_missed: list[float] = []
    for cut in missed:
        cut = round_time(cut)
        index = next(
            (
                position
                for position, shot in enumerate(working)
                if shot["start"] + MIN_SHOT_SECONDS < cut < shot["end"] - MIN_SHOT_SECONDS
            ),
            None,
        )
        if index is None:
            if any(abs(cut - shot["start"]) <= 0.001 or abs(cut - shot["end"]) <= 0.001 for shot in working):
                continue
            raise ReviewError(f"missed cut {cut:.3f}s is not inside any shot or leaves a degenerate shot")
        shot = working[index]
        left = dict(shot)
        right = dict(shot)
        left["end"] = cut
        right["start"] = cut
        right["transition_in"] = "cut"
        left["source"] = "manual"
        right["source"] = "manual"
        working[index : index + 1] = [left, right]
        applied_missed.append(cut)

    shots: list[Shot] = []
    for index, payload in enumerate(working, start=1):
        shots.append(
            Shot(
                shot_id=f"S{index:03d}",
                start=round_time(payload["start"]),
                end=round_time(payload["end"]),
                transition_in="start" if index == 1 else payload.get("transition_in", "cut"),
                source=payload.get("source", "detected"),
            )
        )

    manual = _manual_cuts_after(table.manual_cuts, removed_boundaries, applied_missed)
    corrected = ShotTable(
        video=table.video,
        detector=table.detector,
        shots=shots,
        manual_cuts=manual,
        schema_version=table.schema_version,
    )
    report = validate_shot_table(corrected)
    if not report.ok:
        failed = ", ".join(check.id for check in report.failed)
        raise ReviewError(f"reviewed shot table failed quality gates: {failed}")
    return corrected


def _false_cut_ids(flags: dict[str, Any]) -> set[str]:
    values = flags.get("falseCuts", [])
    if not isinstance(values, list):
        raise ReviewError("'falseCuts' must be a list")
    result: set[str] = set()
    for value in values:
        if isinstance(value, dict):
            shot_id = value.get("shot_id")
        else:
            shot_id = value
        if not shot_id:
            raise ReviewError("every false cut needs a shot_id")
        result.add(str(shot_id))
    return result


def _missed_cut_times(flags: dict[str, Any]) -> list[float]:
    values = flags.get("missedCuts", [])
    if not isinstance(values, list):
        raise ReviewError("'missedCuts' must be a list")
    times: list[float] = []
    for value in values:
        try:
            times.append(round_time(float(value)))
        except (TypeError, ValueError) as error:
            raise ReviewError(f"invalid missed cut time: {value!r}") from error
    return sorted(set(times))


def _manual_cuts_after(
    original: list[float],
    removed: list[float],
    added: list[float],
) -> list[float]:
    kept = [
        cut
        for cut in original
        if not any(abs(cut - boundary) <= 0.001 for boundary in removed)
    ]
    merged = sorted({round_time(cut) for cut in [*kept, *added] if cut > 0})
    return merged


_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>auto-shot 切点检查</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; background: #14171c; color: #e6e8eb; }
  .layout { display: grid; grid-template-columns: minmax(420px, 1.15fr) minmax(420px, 1fr); gap: 18px; padding: 18px; }
  .player-pane { position: sticky; top: 18px; align-self: start; }
  h1 { font-size: 18px; margin: 0 0 6px; }
  .source { color: #9aa4b2; font-size: 12px; overflow-wrap: anywhere; }
  video { width: 100%; background: #000; border-radius: 8px; margin: 12px 0; }
  .controls { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  button, select { background: #232a33; color: #e6e8eb; border: 1px solid #3a4350; border-radius: 6px; padding: 6px 10px; font: inherit; cursor: pointer; }
  button:hover, select:hover { background: #2d3642; }
  button.primary { background: #2f5d8a; border-color: #3d75ab; }
  button.danger { border-color: #7a3b3b; }
  .status { margin: 10px 0 0; padding: 8px 10px; background: #1d232b; border-radius: 6px; color: #cfd6df; font-variant-numeric: tabular-nums; min-height: 36px; }
  .hint { color: #9aa4b2; font-size: 12px; margin: 10px 0 0; }
  .list-pane { min-width: 0; }
  .list-head { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; justify-content: space-between; margin-bottom: 8px; }
  .counts { color: #9aa4b2; font-size: 12px; }
  .table-wrap { max-height: calc(100vh - 150px); overflow: auto; border: 1px solid #2b333d; border-radius: 8px; }
  table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
  thead th { position: sticky; top: 0; background: #1d232b; z-index: 1; text-align: left; font-weight: 600; color: #aeb8c5; }
  th, td { padding: 5px 7px; border-bottom: 1px solid #262e38; white-space: nowrap; }
  tbody tr { cursor: pointer; }
  tbody tr:hover { background: #1c2530; }
  tbody tr.active { background: #233f5c; }
  tr.scene-row { cursor: default; }
  tr.scene-row:hover { background: #18212b; }
  tr.scene-row td { background: #18212b; color: #b9c9dc; font-weight: 600; border-top: 1px solid #3a4a5c; white-space: normal; }
  td.id { color: #9fc3e8; }
  td.scene { color: #8fbfe8; font-size: 11px; }
  td.label { color: #c9d3df; font-size: 11px; max-width: 92px; overflow: hidden; text-overflow: ellipsis; }
  td.label.unknown { color: #6f7b89; }
  .detail { margin-top: 10px; padding: 10px 12px; background: #1d232b; border: 1px solid #2b333d; border-radius: 8px; color: #cfd6df; font-size: 13px; line-height: 1.55; }
  .detail-title { color: #f0c674; font-weight: 600; margin-bottom: 4px; }
  .detail-line { color: #aeb8c5; }
  .detail-line b { color: #e6e8eb; font-weight: 600; }
  .detail a { color: #8fbfe8; }
  .scene-cards { margin-top: 14px; }
  .scene-cards h2 { font-size: 14px; color: #aeb8c5; margin: 0 0 6px; }
  .scene-card { display: inline-block; vertical-align: top; width: 260px; margin: 0 6px 6px 0; padding: 7px 9px; background: #1b232d; border: 1px solid #2b3a4a; border-radius: 7px; cursor: pointer; font-size: 12px; color: #c8d4e2; }
  .scene-card:hover { background: #223142; }
  .scene-card b { color: #f0c674; }
  .scene-card .scene-summary { color: #9aa4b2; margin-top: 3px; }
  td.dur.short { color: #ffb86b; }
  td.dur.very-short { color: #ff7a7a; }
  .flag { accent-color: #d98c8c; }
  .foot { color: #738091; font-size: 12px; margin-top: 10px; }
  @media (max-width: 980px) { .layout { grid-template-columns: 1fr; } .player-pane { position: static; } .table-wrap { max-height: 65vh; } }
</style>
</head>
<body>
<div class="layout">
  <div class="player-pane">
    <h1>auto-shot 切点检查</h1>
    <div class="source">__SOURCE__</div>
    <div class="source">__STATUS__ · 检测器 __DETECTOR__ (threshold __THRESHOLD__) · 生成于 __GENERATED__</div>
    <div class="source">__COUNT__ 镜 · __DURATION__s · VLM 标签 __LABEL_COUNT__ 镜 · 场景 __SCENE_COUNT__ 个 · 点击右侧行跳到切点前 0.6 秒；←/→ 逐切点，空格播放/暂停。</div>
    <video id="player" controls preload="metadata" src="__VIDEO_SRC__"></video>
    <div class="controls">
      <button id="prev" title="上一个切点 (←)">← 上一镜</button>
      <button id="next" title="下一个切点 (→)">下一镜 →</button>
      <button id="pause" title="播放/暂停 (空格)">播放 / 暂停</button>
      <select id="filter" title="按镜头时长筛选">
        <option value="all">全部镜头</option>
        <option value="short">仅短于 1s</option>
        <option value="tiny">仅短于 0.5s</option>
        <option value="long">仅长于 5s</option>
      </select>
      <button id="mark-missed" class="danger" title="把当前时间记为漏切 (m)">标记漏切</button>
      <button id="clear" class="danger">清空标记</button>
      <button id="export" class="primary">导出标记 JSON</button>
    </div>
    <div id="status" class="status">选择一个切点开始检查。</div>
    <div id="detail" class="detail">选择镜头查看 VLM 标签、场景和测量证据。</div>
    <p class="hint">检查方法：在切点前 0.6 秒开始看，确认画面是否真的换了一个镜头。快速剪辑、闪光、叠化、甩镜容易误切；如果切点前后其实是同一镜，勾选该行的“误切”。发现漏切时，播放到缺失切点处按“标记漏切”。</p>
  </div>
  <div class="list-pane">
    <div class="list-head">
      <div class="counts" id="counts"></div>
      <div class="counts">误切标记 <b id="false-count">0</b> · 漏切标记 <b id="missed-count">0</b></div>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>误切</th><th>场景</th><th>镜号</th><th>入点</th><th>出点</th><th>时长</th><th>景别</th><th>运镜</th><th>光线</th><th>色彩</th></tr></thead>
        <tbody id="rows"></tbody>
      </table>
    </div>
    <div class="foot">标记只保存在本浏览器 localStorage，不会写回 shots.json。导出后可用 <code>auto-shot apply-review</code> 生成修正后的镜头表。</div>
    <div class="scene-cards"><h2>场景聚合</h2><div id="scene-cards"></div></div>
  </div>
</div>
<script>
const SOURCE = __SOURCE_JSON__;
const REVIEW_KEY = __REVIEW_KEY_JSON__;
const SHOTS = __SHOTS_JSON__;
const ANNOTATIONS = __ANNOTATIONS_JSON__;
const SCENES = __SCENES_JSON__;
const VIDEO = document.getElementById('player');
const ROWS = document.getElementById('rows');
const FILTER = document.getElementById('filter');
const STATUS = document.getElementById('status');
const DETAIL = document.getElementById('detail');
const SCENE_CARDS = document.getElementById('scene-cards');
const COUNTS = document.getElementById('counts');
const FALSE_COUNT = document.getElementById('false-count');
const MISSED_COUNT = document.getElementById('missed-count');
const STORAGE_KEY = 'autoshot-review:' + REVIEW_KEY;
let flags = loadFlags();
let visible = [];
let active = -1;

function loadFlags() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {falseCuts: [], missedCuts: []};
    const parsed = JSON.parse(raw);
    return {falseCuts: Array.isArray(parsed.falseCuts) ? parsed.falseCuts : [], missedCuts: Array.isArray(parsed.missedCuts) ? parsed.missedCuts : []};
  } catch (error) {
    return {falseCuts: [], missedCuts: []};
  }
}
function saveFlags() {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(flags)); } catch (error) { /* file:// may restrict storage */ }
  updateCounts();
}
function fmt(seconds) {
  const ms = Math.round(seconds * 1000);
  const h = Math.floor(ms / 3600000);
  const m = Math.floor((ms % 3600000) / 60000);
  const s = Math.floor((ms % 60000) / 1000);
  const milli = ms % 1000;
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${String(milli).padStart(3, '0')}`;
}
function filtered() {
  const mode = FILTER.value;
  if (mode === 'short') return SHOTS.filter(shot => shot.duration < 1);
  if (mode === 'tiny') return SHOTS.filter(shot => shot.duration < 0.5);
  if (mode === 'long') return SHOTS.filter(shot => shot.duration > 5);
  return SHOTS;
}
function ann(shot) {
  return ANNOTATIONS[shot.shot_id] || {};
}
function labelValue(shot, key) {
  const item = ann(shot);
  if (!item.label || !item.label.labels) return '—';
  return item.label.labels[key] || '—';
}
function labelTitle(shot, key) {
  const item = ann(shot);
  if (!item.label) return '未标注';
  const value = item.label.labels[key] || 'unknown';
  const confidence = item.label.confidence ? item.label.confidence[key] : null;
  const action = item.label.content ? item.label.content.action : '';
  return `${value}${confidence == null ? '' : ' · ' + Number(confidence).toFixed(2)}${action ? ' · ' + action : ''}`;
}
function appendCell(row, text, className) {
  const cell = document.createElement('td');
  cell.textContent = text;
  if (className) cell.className = className;
  row.appendChild(cell);
}
function render() {
  visible = filtered();
  ROWS.innerHTML = '';
  const fragment = document.createDocumentFragment();
  let lastScene = null;
  visible.forEach((shot, index) => {
    const item = ann(shot);
    if (item.scene_id && item.scene_id !== lastScene) {
      const header = document.createElement('tr');
      header.className = 'scene-row';
      header.id = 'scene-' + item.scene_id;
      const cell = document.createElement('td');
      cell.colSpan = 10;
      cell.textContent = `${item.scene_title}${item.scene_summary ? ' · ' + item.scene_summary : ''}`;
      header.appendChild(cell);
      fragment.appendChild(header);
      lastScene = item.scene_id;
    }
    const tr = document.createElement('tr');
    tr.dataset.index = String(index);
    const flag = document.createElement('input');
    flag.type = 'checkbox';
    flag.className = 'flag';
    flag.checked = flags.falseCuts.includes(shot.shot_id);
    flag.title = '把这个入点标为误切';
    flag.addEventListener('click', event => event.stopPropagation());
    flag.addEventListener('change', () => {
      if (flag.checked) {
        if (!flags.falseCuts.includes(shot.shot_id)) flags.falseCuts.push(shot.shot_id);
      } else {
        flags.falseCuts = flags.falseCuts.filter(id => id !== shot.shot_id);
      }
      saveFlags();
    });
    const flagCell = document.createElement('td');
    flagCell.appendChild(flag);
    tr.appendChild(flagCell);
    appendCell(tr, item.scene_id || '—', 'scene');
    appendCell(tr, shot.shot_id, 'id');
    appendCell(tr, fmt(shot.start));
    appendCell(tr, fmt(shot.end));
    const durCell = document.createElement('td');
    durCell.className = 'dur' + (shot.duration < 0.5 ? ' very-short' : (shot.duration < 1 ? ' short' : ''));
    durCell.textContent = shot.duration.toFixed(3) + 's';
    tr.appendChild(durCell);
    for (const key of ['scale', 'camera', 'lighting', 'color']) {
      const value = labelValue(shot, key);
      const cell = document.createElement('td');
      cell.className = 'label' + (value === '—' || value === 'unknown' ? ' unknown' : '');
      cell.textContent = value;
      cell.title = labelTitle(shot, key);
      tr.appendChild(cell);
    }
    tr.addEventListener('click', () => seek(index));
    fragment.appendChild(tr);
  });
  ROWS.appendChild(fragment);
  active = -1;
  COUNTS.textContent = `显示 ${visible.length} / ${SHOTS.length} 镜`;
  updateCounts();
  highlight();
}
function renderDetail(shot) {
  DETAIL.textContent = '';
  if (!shot) {
    DETAIL.textContent = '选择镜头查看 VLM 标签、场景和测量证据。';
    return;
  }
  const item = ann(shot);
  const title = document.createElement('div');
  title.className = 'detail-title';
  title.textContent = `${shot.shot_id} · ${item.scene_title || '未聚合场景'}`;
  DETAIL.appendChild(title);
  const labels = item.label && item.label.labels ? item.label.labels : null;
  const confidence = item.label && item.label.confidence ? item.label.confidence : {};
  if (!labels) {
    const line = document.createElement('div');
    line.className = 'detail-line';
    line.textContent = '该镜头还没有 VLM 标签。';
    DETAIL.appendChild(line);
  } else {
    const fields = [['scale', '景别'], ['angle', '角度'], ['camera', '运镜'], ['composition', '构图'], ['lighting', '光线'], ['color', '色彩'], ['dof', '景深']];
    const line = document.createElement('div');
    line.className = 'detail-line';
    line.textContent = fields.map(([key, label]) => `${label} ${labels[key] || 'unknown'} (${(confidence[key] ?? 0).toFixed(2)})`).join(' · ');
    DETAIL.appendChild(line);
    const content = item.label.content || {};
    if (content.action) {
      const action = document.createElement('div');
      action.className = 'detail-line';
      action.textContent = `内容：${content.action}`;
      DETAIL.appendChild(action);
    }
    if (Array.isArray(content.subjects) && content.subjects.length) {
      const subjects = document.createElement('div');
      subjects.className = 'detail-line';
      subjects.textContent = `主体：${content.subjects.join('、')}`;
      DETAIL.appendChild(subjects);
    }
    if (item.label.evidence && Object.keys(item.label.evidence).length) {
      const evidence = document.createElement('div');
      evidence.className = 'detail-line';
      evidence.textContent = '标签证据：' + Object.entries(item.label.evidence).map(([key, value]) => `${key}: ${value}`).join('；');
      DETAIL.appendChild(evidence);
    }
  }
  if (item.merged_from && item.merged_from.length) {
    const merged = document.createElement('div');
    merged.className = 'detail-line';
    merged.textContent = `合并来源：${item.merged_from.join('、')}（标签/证据取主镜头 ${item.label_source}）`;
    DETAIL.appendChild(merged);
  }
  const measured = item.evidence && item.evidence.measured ? item.evidence.measured : null;
  if (measured) {
    const line = document.createElement('div');
    line.className = 'detail-line';
    line.textContent = `测量：亮度 ${(measured.brightness ?? 0).toFixed(2)} · 对比度 ${(measured.contrast ?? 0).toFixed(2)} · 饱和度 ${(measured.saturation ?? 0).toFixed(2)} · 运动 ${(measured.motion ?? 0).toFixed(3)} · 人脸 ${(measured.face_ratio == null ? '—' : Number(measured.face_ratio).toFixed(3))}`;
    DETAIL.appendChild(line);
  }
  if (item.evidence && item.evidence.audio) {
    const line = document.createElement('div');
    line.className = 'detail-line';
    line.textContent = `音频：静音比 ${(item.evidence.audio.silence_ratio ?? 0).toFixed(2)}`;
    DETAIL.appendChild(line);
  }
  if (item.evidence && item.evidence.contact_href) {
    const link = document.createElement('a');
    link.href = item.evidence.contact_href;
    link.target = '_blank';
    link.rel = 'noreferrer';
    link.textContent = '打开联系表 / 关键帧';
    DETAIL.appendChild(link);
  }
}
function renderSceneCards() {
  SCENE_CARDS.textContent = '';
  SCENES.forEach(scene => {
    const card = document.createElement('div');
    card.className = 'scene-card';
    const title = document.createElement('b');
    title.textContent = scene.title;
    card.appendChild(title);
    if (scene.summary) {
      const summary = document.createElement('div');
      summary.className = 'scene-summary';
      summary.textContent = scene.summary;
      card.appendChild(summary);
    }
    card.addEventListener('click', () => {
      const header = document.getElementById('scene-' + scene.scene_id);
      if (header) header.scrollIntoView({block: 'center', behavior: 'smooth'});
    });
    SCENE_CARDS.appendChild(card);
  });
}
function seek(index) {
  if (index < 0 || index >= visible.length) return;
  active = index;
  const shot = visible[index];
  VIDEO.currentTime = Math.max(0, shot.start - 0.6);
  VIDEO.play().catch(() => {});
  highlight();
}
function highlight() {
  [...ROWS.children].forEach((row, index) => row.classList.toggle('active', index === active));
  if (active < 0 || active >= visible.length) {
    STATUS.textContent = '选择一个切点开始检查。';
    renderDetail(null);
    return;
  }
  const shot = visible[active];
  STATUS.textContent = `${shot.shot_id}  ${fmt(shot.start)} → ${fmt(shot.end)}  (${shot.duration.toFixed(3)}s)  · 当前 ${fmt(VIDEO.currentTime)}`;
  renderDetail(shot);
}
function step(delta) {
  if (!visible.length) return;
  const next = active < 0 ? (delta > 0 ? 0 : visible.length - 1) : Math.min(visible.length - 1, Math.max(0, active + delta));
  seek(next);
}
function updateCounts() {
  FALSE_COUNT.textContent = String(flags.falseCuts.length);
  MISSED_COUNT.textContent = String(flags.missedCuts.length);
}
function currentShot() {
  if (active >= 0 && active < visible.length) return visible[active];
  return null;
}
function exportFlags() {
  const byId = new Map(SHOTS.map(shot => [shot.shot_id, shot]));
  const payload = {
    source: SOURCE,
    exported_at: new Date().toISOString(),
    falseCuts: flags.falseCuts.map(id => {
      const shot = byId.get(id);
      return shot ? {shot_id: shot.shot_id, start: shot.start, end: shot.end, duration: shot.duration} : {shot_id: id};
    }),
    missedCuts: [...flags.missedCuts].sort((a, b) => a - b)
  };
  const blob = new Blob([JSON.stringify(payload, null, 2) + '\\n'], {type: 'application/json'});
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = 'review-flags.json';
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}
document.getElementById('prev').addEventListener('click', () => step(-1));
document.getElementById('next').addEventListener('click', () => step(1));
document.getElementById('pause').addEventListener('click', () => { VIDEO.paused ? VIDEO.play() : VIDEO.pause(); });
document.getElementById('export').addEventListener('click', exportFlags);
document.getElementById('mark-missed').addEventListener('click', () => {
  const time = Math.round(VIDEO.currentTime * 1000) / 1000;
  if (!flags.missedCuts.includes(time)) flags.missedCuts.push(time);
  saveFlags();
  STATUS.textContent = `已记录漏切：${fmt(time)}（共 ${flags.missedCuts.length} 个）`;
});
document.getElementById('clear').addEventListener('click', () => {
  if (!confirm('清空本页所有误切/漏切标记？')) return;
  flags = {falseCuts: [], missedCuts: []};
  saveFlags();
  render();
});
FILTER.addEventListener('change', render);
VIDEO.addEventListener('timeupdate', () => {
  const time = VIDEO.currentTime;
  const index = visible.findIndex(shot => time >= shot.start && time < shot.end);
  if (index >= 0 && index !== active) {
    active = index;
    highlight();
  } else if (active >= 0) {
    highlight();
  }
});
window.addEventListener('keydown', event => {
  const tag = event.target.tagName;
  if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
  if (event.key === 'ArrowLeft') { event.preventDefault(); step(-1); }
  else if (event.key === 'ArrowRight') { event.preventDefault(); step(1); }
  else if (event.key === ' ') { event.preventDefault(); VIDEO.paused ? VIDEO.play() : VIDEO.pause(); }
  else if (event.key.toLowerCase() === 'm') { document.getElementById('mark-missed').click(); }
  else if (event.key.toLowerCase() === 'f') {
    const shot = currentShot();
    if (!shot) return;
    const index = flags.falseCuts.indexOf(shot.shot_id);
    if (index >= 0) flags.falseCuts.splice(index, 1); else flags.falseCuts.push(shot.shot_id);
    saveFlags();
    const row = ROWS.querySelector(`tr[data-index="${active}"]`);
    const flag = row && row.querySelector('.flag');
    if (flag) flag.checked = index < 0;
  }
});
window.addEventListener('beforeunload', saveFlags);
renderSceneCards();
render();
</script>
</body>
</html>
"""
