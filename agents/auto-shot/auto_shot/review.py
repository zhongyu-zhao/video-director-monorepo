"""Generate a local cut-review page and apply human corrections.

The page is a single HTML file: a video player, the shot list, and
buttons to flag false cuts or mark missed cuts.  It exports a small JSON
file; ``apply_review`` turns that file back into a new shot table with
manual boundaries recorded, without touching the original artifact.
"""

from __future__ import annotations

import html
import json
import os
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
) -> Path:
    """Write a self-contained review page and return its path."""

    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)

    video_path = Path(video).resolve()
    relative = Path(os.path.relpath(video_path, destination.parent.resolve())).as_posix()
    video_src = quote(relative, safe="/.")
    shots_json = json.dumps(
        [shot.to_dict() for shot in table.shots],
        ensure_ascii=False,
    ).replace("</", "<\\/")

    page = _TEMPLATE.replace("__SHOTS_JSON__", shots_json)
    page = page.replace("__VIDEO_SRC__", html.escape(video_src))
    page = page.replace("__SOURCE_JSON__", json.dumps(table.video.path, ensure_ascii=False).replace("</", "<\\/"))
    review_key = f"{table.video.path}|{table.detector.name}:{table.detector.threshold:.3f}|{len(table.shots)}|{table.shots[0].start if table.shots else 0}"
    page = page.replace("__REVIEW_KEY_JSON__", json.dumps(review_key, ensure_ascii=False).replace("</", "<\\/"))
    page = page.replace("__SOURCE__", html.escape(table.video.path))
    page = page.replace("__COUNT__", str(len(table.shots)))
    page = page.replace("__DURATION__", f"{table.video.duration:.3f}")
    destination.write_text(page, encoding="utf-8")
    return destination


def apply_review(table: ShotTable, flags: dict[str, Any]) -> ShotTable:
    """Apply ``falseCuts`` / ``missedCuts`` from a review export.

    False cuts merge a shot into its predecessor.  Missed cuts split the
    containing shot.  The result is renumbered, marked as ``manual`` where
    a human changed a boundary, and validated with the normal gates.
    """

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
  td.id { color: #9fc3e8; }
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
    <div class="source">__COUNT__ 镜 · __DURATION__s · 点击右侧行跳到切点前 0.6 秒；←/→ 逐切点，空格播放/暂停。</div>
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
    <p class="hint">检查方法：在切点前 0.6 秒开始看，确认画面是否真的换了一个镜头。快速剪辑、闪光、叠化、甩镜容易误切；如果切点前后其实是同一镜，勾选该行的“误切”。发现漏切时，播放到缺失切点处按“标记漏切”。</p>
  </div>
  <div class="list-pane">
    <div class="list-head">
      <div class="counts" id="counts"></div>
      <div class="counts">误切标记 <b id="false-count">0</b> · 漏切标记 <b id="missed-count">0</b></div>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>误切</th><th>镜号</th><th>入点</th><th>出点</th><th>时长</th></tr></thead>
        <tbody id="rows"></tbody>
      </table>
    </div>
    <div class="foot">标记只保存在本浏览器 localStorage，不会写回 shots.json。导出后可用 <code>auto-shot apply-review</code> 生成修正后的镜头表。</div>
  </div>
</div>
<script>
const SOURCE = __SOURCE_JSON__;
const REVIEW_KEY = __REVIEW_KEY_JSON__;
const SHOTS = __SHOTS_JSON__;
const VIDEO = document.getElementById('player');
const ROWS = document.getElementById('rows');
const FILTER = document.getElementById('filter');
const STATUS = document.getElementById('status');
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
function render() {
  visible = filtered();
  ROWS.innerHTML = '';
  const fragment = document.createDocumentFragment();
  visible.forEach((shot, index) => {
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
    const idCell = document.createElement('td');
    idCell.className = 'id';
    idCell.textContent = shot.shot_id;
    const startCell = document.createElement('td');
    startCell.textContent = fmt(shot.start);
    const endCell = document.createElement('td');
    endCell.textContent = fmt(shot.end);
    const durCell = document.createElement('td');
    durCell.className = 'dur' + (shot.duration < 0.5 ? ' very-short' : (shot.duration < 1 ? ' short' : ''));
    durCell.textContent = shot.duration.toFixed(3) + 's';
    tr.append(flagCell, idCell, startCell, endCell, durCell);
    tr.addEventListener('click', () => seek(index));
    fragment.appendChild(tr);
  });
  ROWS.appendChild(fragment);
  active = -1;
  COUNTS.textContent = `显示 ${visible.length} / ${SHOTS.length} 镜`;
  updateCounts();
  highlight();
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
    return;
  }
  const shot = visible[active];
  STATUS.textContent = `${shot.shot_id}  ${fmt(shot.start)} → ${fmt(shot.end)}  (${shot.duration.toFixed(3)}s)  · 当前 ${fmt(VIDEO.currentTime)}`;
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
    const flag = ROWS.children[active] && ROWS.children[active].querySelector('.flag');
    if (flag) flag.checked = index < 0;
  }
});
window.addEventListener('beforeunload', saveFlags);
render();
</script>
</body>
</html>
"""
