#!/usr/bin/env python3
"""Credentials file support.

Format (one item per line, key followed by a colon):

    login: my_login
    password: my_password

Empty lines and lines starting with '#' or ';' are ignored. The file is
selected in the GUI when a new tab is created, or passed to the console
client with --credentials.
"""

from __future__ import annotations


def load_credentials(path: str) -> tuple[str, str]:
    """Return (login, password) parsed from the credentials file.

    Raises ValueError with a readable message when the file cannot be
    read or either field is missing.
    """
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            lines = f.readlines()
    except OSError as error:
        raise ValueError(f"cannot read credentials file: {error}")

    login = ""
    password = ""
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key == "login":
            login = value
        elif key in ("password", "passwd"):
            password = value

    if not login and not password:
        raise ValueError(
            f"no 'login:' or 'password:' entries found in {path}")
    if not login:
        raise ValueError(f"'login:' entry missing in {path}")
    if not password:
        raise ValueError(f"'password:' entry missing in {path}")
    return login, password
