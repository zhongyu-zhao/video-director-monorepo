"""M1 evidence layer: proxy, bars, keyframes, measurements, audio.

The shot table stays the fact source.  This module writes an
``evidence.json`` keyed by shot id plus keyframe/contact-sheet files.
Optional face and ASR measurements degrade to ``None`` with a note
rather than a fake zero.
"""

from __future__ import annotations

import bisect
import json
import re
import shutil
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .asr import AsrUnavailable, transcribe
from .models import MediaInfo, ShotTable, round_time
from .probe import probe
from .vision import face_ratio

EVIDENCE_SCHEMA_VERSION = 1
_CROP = re.compile(r"crop=(\d+):(\d+):(\d+):(\d+)")
_PTS = re.compile(r"pts_time:([-+0-9.eE]+)")
_SIGNAL = re.compile(r"lavfi\.signalstats\.(YAVG|YHIGH|YLOW|SATAVG|HUEAVG|YDIF)=([-+0-9.eE]+)")
_SILENCE_START = re.compile(r"silence_start:\s*([-+0-9.eE]+)")
_SILENCE_END = re.compile(r"silence_end:\s*([-+0-9.eE]+)")
_MEAN_VOLUME = re.compile(r"mean_volume:\s*([-+0-9.eE]+) dB")
_MAX_VOLUME = re.compile(r"max_volume:\s*([-+0-9.eE]+) dB")


class EvidenceError(RuntimeError):
    """Raised when proxy/keyframe/measurement extraction fails."""


@dataclass
class EvidenceResult:
    output_dir: Path
    evidence_path: Path
    report_path: Path
    media_path: Path
    proxy_path: Path
    shots: dict[str, dict[str, Any]]
    notes: list[str]


def build_evidence(
    table: ShotTable,
    video: str | Path,
    output_dir: str | Path,
    proxy_width: int = 480,
    keyframes: int = 3,
    face: bool = False,
    face_model: str | Path | None = None,
    asr: bool = False,
    force: bool = False,
) -> EvidenceResult:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []

    proxy = make_proxy(video, destination, proxy_width, force)
    proxy_media = probe(proxy)
    bars = detect_black_bars(proxy, proxy_media)

    frames_dir = destination / "frames"
    contact_dir = destination / "contact-sheets"
    frames = extract_keyframes(proxy, table, frames_dir, contact_dir, keyframes, force)

    signal_frames = measure_signals(proxy)
    signal = _aggregate(table, signal_frames)
    audio_events, volume = measure_audio(video, table)
    asr_segments: list[dict[str, Any]] = []
    if asr:
        try:
            asr_segments = transcribe(video)
        except AsrUnavailable as error:
            notes.append(str(error))

    shots: dict[str, dict[str, Any]] = {}
    for shot in table.shots:
        entries = frames.get(shot.shot_id, {})
        measured = signal.get(shot.shot_id, {})
        if face and entries:
            ratios = [face_ratio(path, face_model) for path in entries.values()]
            known = [value for value in ratios if value is not None]
            measured["face_ratio"] = round(max(known), 4) if known else None
            if not known:
                notes.append("face measurement unavailable (no frames, no detector, or no YuNet model)")
        audio = shot_audio(shot, table, audio_events, volume)
        transcript = [
            segment
            for segment in asr_segments
            if shot.start <= (segment["start"] + segment["end"]) / 2 < shot.end
        ]
        shots[shot.shot_id] = {
            "keyframes": [str(path.relative_to(destination)) for path in entries.values()],
            "contact_sheet": (
                str((contact_dir / f"{shot.shot_id}.jpg").relative_to(destination))
                if (contact_dir / f"{shot.shot_id}.jpg").is_file()
                else None
            ),
            "measured": measured,
            "audio": audio,
            "asr": transcript if asr else None,
        }

    payload = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "video": {
            "path": table.video.path,
            "duration": round_time(table.video.duration),
            "fps": round(float(table.video.fps), 3),
            "width": table.video.width,
            "height": table.video.height,
        },
        "proxy": {
            "path": str(proxy.relative_to(destination)),
            "width": proxy_media.width,
            "height": proxy_media.height,
            "fps": round(float(proxy_media.fps), 3),
        },
        "black_bars": bars["black_bars"],
        "content_rect": bars["content_rect"],
        "shots": shots,
        "audio_events": audio_events,
        "options": {
            "proxy_width": proxy_width,
            "keyframes": keyframes,
            "face": face,
            "face_model": str(face_model) if face_model else None,
            "asr": asr,
        },
        "notes": notes,
    }
    evidence_path = destination / "evidence.json"
    evidence_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    media_path = destination / "media.json"
    media_path.write_text(
        json.dumps(
            {
                "schema_version": EVIDENCE_SCHEMA_VERSION,
                "video": payload["video"],
                "proxy": payload["proxy"],
                "black_bars": bars["black_bars"],
                "content_rect": bars["content_rect"],
                "volume": volume,
                "options": payload["options"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    report_path = destination / "evidence.md"
    report_path.write_text(_render_report(payload), encoding="utf-8")
    return EvidenceResult(
        output_dir=destination,
        evidence_path=evidence_path,
        report_path=report_path,
        media_path=media_path,
        proxy_path=proxy,
        shots=shots,
        notes=notes,
    )


def make_proxy(video: str | Path, output_dir: str | Path, width: int = 480, force: bool = False) -> Path:
    destination = Path(output_dir) / f"proxy-{width}.mp4"
    if destination.is_file() and not force:
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-i",
        str(video),
        "-vf",
        f"scale={width}:-2",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "28",
        "-pix_fmt",
        "yuv420p",
        str(destination),
    ]
    _run(command, "proxy transcode")
    return destination


def detect_black_bars(proxy: str | Path, media: MediaInfo) -> dict[str, Any]:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-i",
        str(proxy),
        "-t",
        "60",
        "-vf",
        "cropdetect=24:2:0",
        "-f",
        "null",
        "-",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise EvidenceError(f"cropdetect failed: {_last_line(completed.stderr)}")
    matches = _CROP.findall(completed.stderr)
    if not matches:
        width, height = media.width, media.height
        return _bars(width, height, width, height, 0, 0)
    counts = Counter((int(w), int(h), int(x), int(y)) for w, h, x, y in matches)
    width, height, x, y = counts.most_common(1)[0][0]
    return _bars(media.width, media.height, width, height, x, y)


def _bars(
    frame_width: int,
    frame_height: int,
    width: int,
    height: int,
    x: int,
    y: int,
) -> dict[str, Any]:
    width = max(1, min(width, frame_width))
    height = max(1, min(height, frame_height))
    x = max(0, min(x, frame_width - width))
    y = max(0, min(y, frame_height - height))
    return {
        "black_bars": {
            "left": x,
            "top": y,
            "right": frame_width - x - width,
            "bottom": frame_height - y - height,
        },
        "content_rect": {
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "x_ratio": round(x / frame_width, 4),
            "y_ratio": round(y / frame_height, 4),
            "width_ratio": round(width / frame_width, 4),
            "height_ratio": round(height / frame_height, 4),
        },
    }


def extract_keyframes(
    proxy: str | Path,
    table: ShotTable,
    frames_dir: str | Path,
    contact_dir: str | Path,
    keyframes: int = 3,
    force: bool = False,
) -> dict[str, dict[str, Path]]:
    if keyframes <= 0:
        raise EvidenceError("keyframes must be positive")
    frames_root = Path(frames_dir)
    contact_root = Path(contact_dir)
    frames_root.mkdir(parents=True, exist_ok=True)
    contact_root.mkdir(parents=True, exist_ok=True)
    fps = table.video.fps
    if fps <= 0:
        raise EvidenceError("video fps is required for keyframe extraction")

    positions = [0.15, 0.5, 0.85] if keyframes == 3 else [
        (index + 1) / (keyframes + 1) for index in range(keyframes)
    ]
    max_frame = max(0, int(table.video.duration * fps) - 1)
    requested: list[tuple[str, int, int]] = []
    frame_numbers: set[int] = set()
    for shot in table.shots:
        for index, position in enumerate(positions, start=1):
            time = shot.start + shot.duration * position
            frame = min(max_frame, max(0, round(time * fps)))
            requested.append((shot.shot_id, index, frame))
            frame_numbers.add(frame)
    ordered = sorted(frame_numbers)
    expression = "+".join(f"eq(n,{number})" for number in ordered)
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-i",
        str(proxy),
        "-vf",
        f"select='{expression}',scale=480:-2",
        "-fps_mode",
        "vfr",
        "-q:v",
        "3",
        "-f",
        "image2",
        str(frames_root / "frame-%06d.jpg"),
    ]
    _run(command, "keyframe extraction")
    frame_paths: dict[int, Path] = {}
    for position, number in enumerate(ordered, start=1):
        path = frames_root / f"frame-{position:06d}.jpg"
        if path.is_file():
            frame_paths[number] = path

    available = sorted(frame_paths)
    if not available:
        raise EvidenceError("keyframe extraction produced no frames")
    result: dict[str, dict[str, Path]] = {}
    for shot_id, index, frame in requested:
        source = frame_paths.get(frame)
        if source is None:
            # Near the end of a video, duration*fps can overshoot the last
            # decoded frame; use the nearest earlier extracted frame.
            fallback = max((number for number in available if number <= frame), default=available[0])
            source = frame_paths[fallback]
        destination = frames_root / f"{shot_id}-k{index}.jpg"
        if force or not destination.is_file():
            shutil.copyfile(source, destination)
        result.setdefault(shot_id, {})[f"k{index}"] = destination

    for shot in table.shots:
        paths = result.get(shot.shot_id)
        if not paths:
            continue
        contact = contact_root / f"{shot.shot_id}.jpg"
        if force or not contact.is_file():
            command = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
            for path in paths.values():
                command += ["-i", str(path)]
            command += [
                "-filter_complex",
                f"hstack=inputs={len(paths)}",
                "-frames:v",
                "1",
                str(contact),
            ]
            _run(command, f"contact sheet {shot.shot_id}")
    for path in frame_paths.values():
        path.unlink(missing_ok=True)
    return result


def measure_signals(proxy: str | Path) -> list[dict[str, float]]:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-i",
        str(proxy),
        "-vf",
        "signalstats,metadata=print",
        "-f",
        "null",
        "-",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise EvidenceError(f"signalstats failed: {_last_line(completed.stderr)}")
    frames: list[dict[str, float]] = []
    current: dict[str, float] = {}
    time: float | None = None
    for line in completed.stderr.splitlines():
        match = _PTS.search(line)
        if match:
            if time is not None and current:
                frames.append({"time": time, **current})
            try:
                time = float(match.group(1))
            except ValueError:
                time = None
            current = {}
            continue
        match = _SIGNAL.search(line)
        if match and time is not None:
            try:
                current[match.group(1)] = float(match.group(2))
            except ValueError:
                continue
    if time is not None and current:
        frames.append({"time": time, **current})
    return frames


def _aggregate(table: ShotTable, frames: list[dict[str, float]]) -> dict[str, dict[str, float]]:
    starts = [shot.start for shot in table.shots]
    buckets: dict[str, list[dict[str, float]]] = {shot.shot_id: [] for shot in table.shots}
    for frame in frames:
        index = bisect.bisect_right(starts, frame["time"]) - 1
        if 0 <= index < len(table.shots):
            buckets[table.shots[index].shot_id].append(frame)

    result: dict[str, dict[str, float]] = {}
    for shot in table.shots:
        values = buckets[shot.shot_id]
        if not values:
            continue
        result[shot.shot_id] = {
            "brightness": _mean([item.get("YAVG", 0.0) / 255.0 for item in values]),
            "contrast": _mean([
                (item.get("YHIGH", 0.0) - item.get("YLOW", 0.0)) / 255.0 for item in values
            ]),
            "saturation": _mean([item.get("SATAVG", 0.0) / 255.0 for item in values]),
            "hue": _mean([item.get("HUEAVG", 0.0) / 360.0 for item in values]),
            "motion": _mean([item.get("YDIF", 0.0) / 255.0 for item in values]),
        }
    return result


def measure_audio(video: str | Path, table: ShotTable) -> tuple[list[dict[str, Any]], dict[str, float | None]]:
    if not table.video.has_audio:
        return [], {"mean_db": None, "max_db": None}
    command = [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-i",
        str(video),
        "-vn",
        "-af",
        "silencedetect=noise=-35dB:d=0.5",
        "-f",
        "null",
        "-",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    events: list[dict[str, Any]] = []
    starts: list[float] = []
    ends: list[float] = []
    for line in completed.stderr.splitlines():
        match = _SILENCE_START.search(line)
        if match:
            starts.append(float(match.group(1)))
            continue
        match = _SILENCE_END.search(line)
        if match:
            ends.append(float(match.group(1)))
    for start, end in zip(starts, ends):
        events.append({"kind": "silence", "start": round(start, 3), "end": round(end, 3)})
    volume = _volume(video)
    return events, volume


def _volume(video: str | Path) -> dict[str, float | None]:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-i",
        str(video),
        "-vn",
        "-af",
        "volumedetect",
        "-f",
        "null",
        "-",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    mean = _MEAN_VOLUME.search(completed.stderr)
    maximum = _MAX_VOLUME.search(completed.stderr)
    return {
        "mean_db": float(mean.group(1)) if mean else None,
        "max_db": float(maximum.group(1)) if maximum else None,
    }


def shot_audio(
    shot: Any,
    table: ShotTable,
    events: list[dict[str, Any]],
    volume: dict[str, float | None],
) -> dict[str, Any]:
    silence = 0.0
    for event in events:
        if event["kind"] != "silence":
            continue
        overlap = min(shot.end, event["end"]) - max(shot.start, event["start"])
        if overlap > 0:
            silence += overlap
    return {
        "silence_ratio": round(min(1.0, silence / shot.duration), 3) if shot.duration > 0 else 0.0,
        "mean_db": volume.get("mean_db"),
        "max_db": volume.get("max_db"),
    }


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def _render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# M1 证据层",
        "",
        f"- 视频：`{payload['video']['path']}`",
        f"- Proxy：{payload['proxy']['width']}x{payload['proxy']['height']}",
        f"- 黑边：{payload['black_bars']}",
        f"- 内容区：{payload['content_rect']}",
        f"- 音频事件：{len(payload['audio_events'])}",
        "",
        "| 镜号 | 关键帧 | 亮度 | 对比度 | 饱和度 | 运动 | 人脸占比 | 静音比 |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for shot_id, entry in payload["shots"].items():
        measured = entry["measured"]
        lines.append(
            f"| {shot_id} | {len(entry['keyframes'])} | {measured.get('brightness', 0):.3f} | "
            f"{measured.get('contrast', 0):.3f} | {measured.get('saturation', 0):.3f} | "
            f"{measured.get('motion', 0):.3f} | {_fmt(measured.get('face_ratio'))} | "
            f"{entry['audio'].get('silence_ratio', 0):.3f} |"
        )
    if payload["notes"]:
        lines += ["", "## 备注", ""]
        lines += [f"- {note}" for note in payload["notes"]]
    lines.append("")
    return "\n".join(lines)


def _fmt(value: Any) -> str:
    return "-" if value is None else f"{float(value):.3f}"


def _run(command: list[str], action: str) -> None:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise EvidenceError(f"{action} failed: {_last_line(completed.stderr)}")


def _last_line(text: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return lines[-1] if lines else "unknown ffmpeg error"
