#!/usr/bin/env python3
"""Server error-message decoding.

Loads the element client's server_error.txt (UTF-16LE table of
`<code> "<message>"` lines) and translates numeric error codes received
in game command 25 (ERROR_MESSAGE) into human-readable text.
"""

from __future__ import annotations

import os
import re

DEFAULT_ERROR_FILE = "server_error.txt"

_ENTRY = re.compile(r'^\s*(\d+)\s+"(.*)"\s*$')


def load_error_messages(path: str = DEFAULT_ERROR_FILE) -> dict[int, str]:
    """Parse server_error.txt into {code: message} (empty if unreadable)."""
    try:
        with open(path, "rb") as f:
            text = f.read().decode("utf-16")
    except (OSError, UnicodeError):
        return {}
    messages: dict[int, str] = {}
    for line in text.splitlines():
        match = _ENTRY.match(line)
        if match:
            # first occurrence wins, like the native client's table load
            messages.setdefault(int(match.group(1)), match.group(2))
    return messages


def find_error_file(config: dict) -> str:
    """Error-table path: config override, else next to this module."""
    override = config.get("server_error_file")
    if override:
        return override
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        DEFAULT_ERROR_FILE)
