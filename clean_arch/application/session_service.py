"""Application-level session lifecycle, independent from the GUI toolkit."""

from __future__ import annotations

from collections.abc import Callable

from clean_arch.domain.models import LogLine, SessionSettings
from clean_arch.domain.ports import SessionWorker


class SessionService:
    """Run one account session and translate failures into log events."""

    def __init__(self, worker: SessionWorker):
        self._worker = worker

    def run(self, settings: SessionSettings,
            emit: Callable[[LogLine], None]) -> int:
        try:
            return self._worker.run(settings, emit)
        except Exception as error:
            emit(LogLine(f"[Clean Arch] Worker error: {error}", "error"))
            return 1
