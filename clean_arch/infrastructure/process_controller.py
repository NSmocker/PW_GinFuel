"""Own one worker subprocess and its IO lifecycle."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
from collections.abc import Iterable

from clean_arch.domain.models import LogLine, SessionMode, SessionSettings


class WorkerProcess:
    """Generation-aware process wrapper used by one GUI tab."""

    def __init__(self, worker_path: str, cwd: str):
        self._worker_path = worker_path
        self._cwd = cwd
        self._process: subprocess.Popen[str] | None = None
        self._events: queue.Queue[LogLine] = queue.Queue()
        self._generation = 0
        self._lock = threading.Lock()

    @property
    def process(self) -> subprocess.Popen[str] | None:
        return self._process

    def start(self, settings: SessionSettings) -> None:
        with self._lock:
            self._generation += 1
        self.stop()
        command = [sys.executable, self._worker_path,
                   "--credentials", settings.credentials_path,
                   "--config", settings.config_path]
        if settings.mode is SessionMode.LOGIN_ONLY:
            command.append("--login-only")
        environment = dict(os.environ, PYTHONIOENCODING="utf-8",
                           PYTHONUNBUFFERED="1")
        try:
            process = subprocess.Popen(
                command, cwd=self._cwd, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                env=environment,
                creationflags=0x08000000 if sys.platform == "win32" else 0)
        except OSError as error:
            self._events.put(LogLine(f"[GUI] Worker start failed: {error}",
                                     "error"))
            return
        with self._lock:
            generation = self._generation
            self._process = process
        threading.Thread(target=self._read_output,
                         args=(process, generation), daemon=True).start()

    def _read_output(self, process: subprocess.Popen[str], generation: int) -> None:
        if process.stdout is None:
            return
        for line in process.stdout:
            with self._lock:
                current = generation == self._generation
            if current:
                self._events.put(LogLine(line.rstrip("\r\n")))
        return_code = process.wait()
        with self._lock:
            current = generation == self._generation
        if current:
            self._events.put(LogLine(
                f"[GUI] Worker exited with code {return_code}", "lifecycle"))

    def send_control(self, command: str) -> None:
        process = self._process
        if not process or process.poll() is not None or process.stdin is None:
            return
        try:
            process.stdin.write(command + "\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            pass

    def stop(self) -> None:
        process = self._process
        if not process or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    def restart(self, settings: SessionSettings) -> None:
        self.start(settings)

    def clear_events(self) -> None:
        while True:
            try:
                self._events.get_nowait()
            except queue.Empty:
                return

    def poll(self) -> Iterable[LogLine]:
        while True:
            try:
                yield self._events.get_nowait()
            except queue.Empty:
                return
