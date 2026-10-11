"""Identity boundary for the legacy-compatible Windows probes."""

from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from machine_info import build_fingerprint, build_machine_info  # noqa: E402

__all__ = ["build_fingerprint", "build_machine_info"]
