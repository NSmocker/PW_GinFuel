#!/usr/bin/env python3
"""Config-file loading for the console client."""

from __future__ import annotations

import os
import re

DEFAULT_CONFIG_FILE = "console_client_config.txt"


def load_config(path: str = DEFAULT_CONFIG_FILE) -> dict:
    """Load key=value settings from the config file (may not exist)."""
    config: dict = {}
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return config
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        # strip inline comments after the value
        for marker in ("#", ";"):
            pos = line.find(marker)
            if pos >= 0:
                line = line[:pos].rstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        config[key.strip().lower()] = value.strip()
    return config


def resolve_server_from_userdata(folder: str) -> tuple[str, int]:
    """Read host/port from the client's userdata/currentserver.ini."""
    ini_path = os.path.join(folder, "currentserver.ini")
    match = None
    try:
        with open(ini_path, "r", encoding="mbcs", errors="replace") as f:
            match = re.search(r"CurrentServerAddress=(\d+):([\d.]+)",
                              f.read())
    except OSError:
        pass
    if not match:
        raise ValueError(f"could not read server address from {ini_path}")
    return match.group(2), int(match.group(1))


def config_int(config: dict, key: str) -> int | None:
    """Parse an int config value; accepts decimal and hex (incl. 0x-prefix)."""
    value = config.get(key)
    if value is None:
        return None
    try:
        return int(value)          # decimal (incl. negative)
    except ValueError:
        pass
    try:
        return int(value, 16)      # 0x-prefixed or plain hex like 8010007c
    except ValueError:
        return None
