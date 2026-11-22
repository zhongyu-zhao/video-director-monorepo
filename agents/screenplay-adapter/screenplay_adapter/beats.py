"""Structural beat templates.

These are scaffolds for pacing checks and scene briefs, not creative judgment.
A feature reuses Save the Cat's 15-beat landmarks (approximate percentages);
episodic formats use a per-episode arc with a hook and a cliffhanger, which is
the relevant rhythm for short drama and series.  The templates are data: a new
format is a new list, not a new branch in the planner.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Beat:
    id: str
    label: str
    start: float
    end: float
    guidance: str

    def contains(self, progress: float) -> bool:
        return self.start <= progress < self.end


# Percentages are approximate landmarks, not a claim that every story must hit
# them.  Intervals are made contiguous so scene assignment stays monotonic.
FEATURE_BEATS: tuple[Beat, ...] = (
    Beat("opening_image", "开场画面", 0.00, 0.02, "用一个可拍的画面建立主角的日常世界和基调。"),
    Beat("theme_stated", "主题陈述", 0.02, 0.08, "让某个人物说出一句点题的话，不要解释主题。"),
    Beat("setup", "铺垫", 0.08, 0.12, "展示主角的缺陷、关系和日常，让观众理解他失去什么。"),
    Beat("catalyst", "催化剂", 0.12, 0.15, "一个事件打破日常，故事真正开始。"),
    Beat("debate", "争论", 0.15, 0.22, "主角抗拒、犹豫或准备，展示进入新世界的代价。"),
    Beat("break_into_two", "进入第二幕", 0.22, 0.24, "主角做出不可逆的选择，进入新世界。"),
    Beat("b_story", "B 故事", 0.24, 0.28, "启动爱情、友谊或师徒副线，承载主题。"),
    Beat("fun_and_games", "游戏与乐趣", 0.28, 0.50, "兑现前提的段落：主角在新世界行动、升级、犯错。"),
    Beat("midpoint", "中点", 0.50, 0.55, "假胜利或假失败，抬高赌注，收窄目标。"),
    Beat("bad_guys_close_in", "坏人逼近", 0.55, 0.73, "外部/内部压力同时收紧，主角的旧办法失效。"),
    Beat("all_is_lost", "一切失去", 0.73, 0.78, "最害怕的事发生，主角跌到最低点。"),
    Beat("dark_night", "灵魂黑夜", 0.78, 0.82, "消化失败，完成内在转变前的停顿。"),
    Beat("break_into_three", "进入第三幕", 0.82, 0.85, "新信息让主角知道必须做什么。"),
    Beat("finale", "终局", 0.85, 0.98, "正面对决，主角用学到的教训解决核心问题。"),
    Beat("final_image", "结束画面", 0.98, 1.00, "与开场画面呼应的“之后”画面，展示变化。"),
)

SERIES_BEATS: tuple[Beat, ...] = (
    Beat("cold_open", "开场钩子", 0.00, 0.08, "用冲突或悬念在前几秒抓住观众。"),
    Beat("setup", "建置", 0.08, 0.25, "交代本集目标、人物关系和阻力。"),
    Beat("escalation", "升级", 0.25, 0.50, "阻力升级，主角的第一次尝试失败。"),
    Beat("turn", "转折", 0.50, 0.70, "信息或关系反转，主角找到新方向。"),
    Beat("complication", "复杂化", 0.70, 0.90, "代价出现，目标看似要失败。"),
    Beat("cliffhanger", "结尾卡点", 0.90, 1.00, "在最大悬念处收束，给下一集一个必须看的理由。"),
)

SHORT_DRAMA_BEATS: tuple[Beat, ...] = (
    Beat("hook", "开场钩子", 0.00, 0.08, "前几秒给出冲突、羞辱或悬念，不要热场。"),
    Beat("escalation", "升级", 0.08, 0.45, "立刻升级矛盾，让主角做出反应。"),
    Beat("turn", "反转", 0.45, 0.75, "给出信息差反转或身份/立场翻转。"),
    Beat("cliffhanger", "结尾卡点", 0.75, 1.00, "在最想看下一集的位置切断。"),
)

_TEMPLATES = {
    "feature": FEATURE_BEATS,
    "series": SERIES_BEATS,
    "short-drama": SHORT_DRAMA_BEATS,
}


def beats_for(format: str) -> tuple[Beat, ...]:
    try:
        return _TEMPLATES[format]
    except KeyError as error:
        raise ValueError(f"unknown format: {format}") from error


def beat_for(progress: float, beats: tuple[Beat, ...]) -> Beat:
    clamped = min(max(progress, 0.0), 1.0)
    if clamped >= 1.0:
        clamped = 0.999999
    for beat in beats:
        if beat.contains(clamped):
            return beat
    return beats[-1]


def beat_index(beat_id: str, format: str) -> int:
    for index, beat in enumerate(beats_for(format)):
        if beat.id == beat_id:
            return index
    return -1


def beat_label(beat_id: str, format: str) -> str:
    for beat in beats_for(format):
        if beat.id == beat_id:
            return beat.label
    return beat_id


def beat_guidance(beat_id: str, format: str) -> str:
    for beat in beats_for(format):
        if beat.id == beat_id:
            return beat.guidance
    return ""
