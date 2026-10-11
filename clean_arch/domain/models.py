"""Framework-independent application models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SessionMode(str, Enum):
    WORLD = "world"
    LOGIN_ONLY = "login_only"


@dataclass(frozen=True)
class AccountRef:
    credentials_path: str
    login: str


@dataclass(frozen=True)
class SessionSettings:
    config_path: str
    credentials_path: str
    mode: SessionMode = SessionMode.WORLD


@dataclass(frozen=True)
class LogLine:
    text: str
    source: str = "worker"


@dataclass(frozen=True)
class ProcessExited:
    return_code: int
