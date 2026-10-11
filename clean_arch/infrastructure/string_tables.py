"""Readers for the game's UTF-16LE ``.stf`` string tables."""

from __future__ import annotations

import csv
import io
import os


def load_stf(path: str) -> dict[int, str]:
    """Load ``id<TAB>"text"`` entries from a game string table.

    Missing or malformed optional assets return an empty mapping so protocol
    diagnostics continue to work with symbolic names only.
    """
    try:
        with open(path, "rb") as file:
            text = file.read().decode("utf-16")
    except (OSError, UnicodeError):
        return {}
    result: dict[int, str] = {}
    for row in csv.reader(io.StringIO(text), delimiter="\t"):
        if len(row) < 2:
            continue
        try:
            key = int(row[0].strip())
        except ValueError:
            continue
        result.setdefault(key, row[1])
    return result


def load_game_string_tables(root: str) -> dict[str, dict[int, str]]:
    """Load the three known tables relative to the installed game root."""
    msgbox = os.path.join(root, "msgbox.stf")
    if not os.path.isfile(msgbox):
        msgbox = os.path.join(root, "Interfaces", "MsgBox.stf")
    paths = {
        "ingame": os.path.join(root, "ingame.stf"),
        "loginui": os.path.join(root, "loginui.stf"),
        "msgbox": msgbox,
    }
    return {name: load_stf(path) for name, path in paths.items()}
