"""Ports used by the application layer."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Protocol

from .models import LogLine, SessionSettings


class SessionWorker(Protocol):
    def run(self, settings: SessionSettings,
            emit: Callable[[LogLine], None]) -> int: ...


class ProcessController(Protocol):
    def start(self, settings: SessionSettings) -> None: ...
    def stop(self) -> None: ...
    def restart(self, settings: SessionSettings) -> None: ...
    def poll(self) -> Iterable[LogLine]: ...
