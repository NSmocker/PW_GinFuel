"""Structured interpretation of worker output for presentation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LogPresentation:
    pane: str
    color: str
    actions: tuple[str, ...] = ()


QUEST_MARKERS = (
    ("Квест здано", "ok_return"),
    ("Квест взято", "ok_accept"),
    ("Sent Task return", "reset_return"),
    ("Sent Task accept", "reset_accept"),
    ("Quest return confirmed", "ok_return"),
    ("Quest accept confirmed", "ok_accept"),
    ("removed (returned)", "ok_return"),
    ("added (accepted)", "ok_accept"),
    ("No confirmation of quest return", "fail_return"),
    ("No confirmation of quest accept", "fail_accept"),
    ("No reply to Task return", "fail_return"),
    ("No reply to Task accept", "fail_accept"),
    ("No confirmation for Task return", "fail_return"),
    ("No confirmation for Task accept", "fail_accept"),
)


def classify(text: str) -> LogPresentation:
    actions = tuple(action for marker, action in QUEST_MARKERS
                    if marker in text)
    pane = "quest" if any(word in text.lower()
                           for word in ("quest", "task", "npc")) else "connection"
    if any(action.startswith("ok_") for action in actions):
        color = "success"
    elif any(action.startswith("fail_") for action in actions):
        color = "error"
    else:
        color = "default"
    return LogPresentation(pane, color, actions)
