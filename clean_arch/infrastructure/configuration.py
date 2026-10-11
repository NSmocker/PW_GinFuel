"""Configuration adapters kept outside the application layer."""

from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from credentials import load_credentials  # noqa: E402

__all__ = ["load_credentials"]
