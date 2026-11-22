"""Test fixtures: a small synthetic novel, project helpers and a fake provider."""

from __future__ import annotations

import io
import json
import threading
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from screenplay_adapter.cast import extract_cast
from screenplay_adapter.models import AdaptationPlan, Dialogue, Heading, SceneDraft, SourceDocument
from screenplay_adapter.plan import build_plan, make_brief, render_briefs
from screenplay_adapter.project import save_briefs, save_draft, save_plan, write_source
from screenplay_adapter.source import parse_source

NOVEL = """# 雨夜

## 第一章 咖啡馆

林昭推开咖啡馆的门，雨水顺着伞尖滴在木地板上。她看见顾远坐在窗边，面前放着两杯已经凉透的咖啡。

“你迟到了。”顾远说。

“路上堵车。”林昭把伞靠在墙边，坐了下来。她注意到他的袖口有一道新的划痕。

顾远笑了笑：“我不介意。反正我已经等了三年。”

林昭没有回答。窗外的雨更大了，街灯把水洼照得发白。她从包里取出一个信封，推到桌子中间。

## 第二章 信封

顾远没有碰信封。“这是什么？”

“你一直在找的东西。”林昭说，“看完之后，你就知道那天晚上发生了什么。”

他沉默了很久，最后把信封收进外套内袋。“你为什么现在才给我？”

林昭站起身，拿起伞。“因为我需要你先欠我一个人情。”

## 第三章 天台

凌晨两点，顾远站在天台边缘，城市的灯在他脚下铺开。他拆开信封，里面只有一张旧照片和一把钥匙。

“你来了。”身后传来林昭的声音。

顾远没有回头。“照片上的人是谁？”

“你父亲。”林昭说，“钥匙能打开他留下的仓库。明天之后，我们两清。”

顾远终于转身。他看见她眼里的疲惫，也看见她握伞的手在发抖。
"""


def make_document(text: str = NOVEL, title: str = "雨夜") -> SourceDocument:
    return parse_source(text, path="source/source.md", title=title)


def make_plan(
    root: Path | None = None,
    *,
    episodes: int = 3,
    episode_minutes: float = 2.0,
    scene_seconds: float = 45.0,
    format: str = "short-drama",
    mode: str = "adapt",
    text: str = NOVEL,
) -> tuple[SourceDocument, AdaptationPlan]:
    document = make_document(text)
    brief = make_brief(
        "雨夜",
        format,
        episodes=episodes,
        episode_minutes=episode_minutes,
        scene_seconds=scene_seconds,
        language="zh",
        mode=mode,
    )
    plan = build_plan(document, brief, extract_cast(document))
    if root is not None:
        write_source(root, document.text)
        save_plan(root, plan)
        save_briefs(root, render_briefs(plan, document))
    return document, plan


def make_drafts(plan: AdaptationPlan, *, character: str = "林昭", basis: str = "adapted") -> dict[str, SceneDraft]:
    drafts: dict[str, SceneDraft] = {}
    for scene in plan.scenes:
        speaker = scene.cast[0] if scene.cast else character
        action = ("雨水敲打玻璃，林昭把伞靠在墙边。",)
        dialogue = (Dialogue(character=speaker, line="我来了。", parenthetical="低声", basis=basis),)
        drafts[scene.id] = SceneDraft(
            scene_id=scene.id,
            heading=Heading(int_ext="INT", location="咖啡馆", time="NIGHT"),
            action=action,
            dialogue=dialogue,
            plan_hash=plan.plan_hash,
            source_sha256=str(plan.source.get("sha256", "")),
            provider="test",
            model="fake",
            prompt_sha256="0" * 64,
        )
    return drafts


def save_drafts(root: Path, drafts: dict[str, SceneDraft]) -> None:
    for draft in drafts.values():
        save_draft(root, draft)


def run_cli(main, *arguments: str) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = main(list(arguments))
    return code, stdout.getvalue(), stderr.getvalue()


def scene_payload(scene_id: str, *, character: str = "林昭", basis: str = "adapted") -> dict[str, Any]:
    return {
        "scene_id": scene_id,
        "heading": {"int_ext": "INT", "location": "咖啡馆", "time": "NIGHT"},
        "action": ["雨水敲打玻璃。林昭把伞靠在墙边。"],
        "dialogue": [
            {"character": character, "parenthetical": "低声", "line": "我来了。", "basis": basis}
        ],
        "transition": "",
        "notes": "",
    }


def start_fake_server(
    builder: Callable[[dict[str, Any]], tuple[int, dict[str, Any]]],
) -> tuple[ThreadingHTTPServer, int]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - stdlib naming
            length = int(self.headers.get("content-length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            status, payload = builder(body)
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, server.server_address[1]


def prompt_scene_id(request: dict[str, Any]) -> str:
    content = request["messages"][1]["content"]
    marker = "场号："
    start = content.index(marker) + len(marker)
    return content[start:].split()[0].strip()


def stop_server(server: ThreadingHTTPServer) -> None:
    server.shutdown()
    server.server_close()
