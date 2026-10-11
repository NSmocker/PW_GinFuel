"""Human-readable protocol and game-command names from the client source.

The C++ headers are the authoritative ID registry. Parsing them at startup
keeps the Python client aligned with the exact source checkout without
duplicating hundreds of enum entries by hand.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

DEFAULT_SOURCE_ROOT = os.environ.get(
    "PW_CLIENT_SOURCE", r"B:\Git\PW_ClientSource\client")

_ASSIGNMENT = re.compile(r"^\s*([A-Za-z_]\w*)\s*(?:=\s*([^,]+))?\s*,?\s*$")


@dataclass(frozen=True)
class ProtocolCatalog:
    protocols: dict[int, str]
    c2s_commands: dict[int, str]
    s2c_commands: dict[int, str]
    errors: dict[int, str]
    source_root: str | None = None

    def protocol_name(self, value: int) -> str:
        return self.protocols.get(value, f"UNKNOWN_PROTOCOL_{value}")

    def command_name(self, direction: str, value: int) -> str:
        table = self.c2s_commands if direction == "C2S" else self.s2c_commands
        return table.get(value, f"UNKNOWN_{direction}_COMMAND_{value}")

    def error_name(self, value: int) -> str:
        return self.errors.get(value, f"UNKNOWN_ERROR_{value}")


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as file:
        return file.read()


def _enum_body(text: str, marker: str, start: int = 0) -> str:
    marker_pos = text.find(marker, start)
    if marker_pos < 0:
        return ""
    brace = text.find("{", marker_pos)
    if brace < 0:
        return ""
    depth = 0
    for position in range(brace, len(text)):
        if text[position] == "{":
            depth += 1
        elif text[position] == "}":
            depth -= 1
            if depth == 0:
                return text[brace + 1:position]
    return ""


def _parse_enum(body: str, initial: int = 0) -> dict[int, str]:
    result: dict[int, str] = {}
    value = initial
    for raw in body.splitlines():
        line = raw.split("//", 1)[0].strip()
        if not line:
            continue
        for item in line.split(","):
            item = item.strip()
            if not item:
                continue
            match = _ASSIGNMENT.match(item + ",")
            if not match:
                continue
            name, expression = match.groups()
            if expression:
                expression = expression.strip()
                try:
                    value = int(expression, 0)
                except ValueError:
                    continue
            result[value] = name
            value += 1
    return result


def load_catalog(source_root: str = DEFAULT_SOURCE_ROOT) -> ProtocolCatalog:
    """Load protocol, C2S, S2C and error names from the source checkout."""
    callid = os.path.join(source_root, "CElement", "CElementClient",
                          "Network", "callid.hxx")
    game_types = os.path.join(source_root, "CElement", "CElementClient",
                              "Network", "EC_GPDataType.h")
    gnetdef = os.path.join(source_root, "CElement", "CElementClient",
                           "Network", "gnetdef.h")
    try:
        callid_text = _read(callid)
        game_text = _read(game_types)
        error_text = _read(gnetdef)
    except OSError:
        return fallback_catalog()

    protocols = _parse_enum(_enum_body(callid_text, "enum ProtocolType"))
    s2c_start = game_text.find("namespace S2C")
    c2s_start = game_text.find("namespace C2S")
    s2c_marker = game_text.find("Commands", s2c_start)
    c2s_marker = game_text.find("Commands", c2s_start)
    s2c_commands = _parse_enum(_enum_body(game_text, "enum", s2c_marker))
    c2s_commands = _parse_enum(_enum_body(game_text, "enum", c2s_marker))
    errors = _parse_enum(_enum_body(error_text, "enum ErrCode"))
    return ProtocolCatalog(protocols, c2s_commands, s2c_commands, errors,
                           source_root)


def fallback_catalog() -> ProtocolCatalog:
    return ProtocolCatalog({
        1: "PROTOCOL_CHALLENGE", 2: "PROTOCOL_KEYEXCHANGE",
        3: "PROTOCOL_RESPONSE", 4: "PROTOCOL_ONLINEANNOUNCE",
        5: "PROTOCOL_ERRORINFO", 34: "PROTOCOL_GAMEDATASEND",
        37: "PROTOCOL_COLLECTCLIENTMACHINEINFO", 70: "PROTOCOL_SELECTROLE",
        71: "PROTOCOL_SELECTROLE_RE", 72: "PROTOCOL_ENTERWORLD",
        82: "PROTOCOL_ROLELIST", 83: "PROTOCOL_ROLELIST_RE",
        90: "PROTOCOL_KEEPALIVE", 143: "PROTOCOL_ACCOUNTLOGINRECORD",
    }, {
        0: "PLAYER_MOVE", 35: "SEVNPC_HELLO", 37: "SEVNPC_SERVE",
        39: "GET_ALL_DATA", 49: "TASK_NOTIFY",
    }, {
        0: "PLAYER_INFO_1", 9: "NPC_INFO_LIST", 25: "ERROR_MESSAGE",
        70: "NPC_GREETING", 106: "TASK_NOTIFY",
    }, {0: "ERR_SUCCESS", 2: "ERR_INVALID_ACCOUNT",
        3: "ERR_INVALID_PASSWORD", 4: "ERR_TIMEOUT"})
