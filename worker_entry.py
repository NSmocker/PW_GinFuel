"""Worker process entrypoint used by the Clean Arch GUI."""

from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from clean_arch.application.session_service import SessionService  # noqa: E402
from clean_arch.domain.models import LogLine, SessionMode, SessionSettings  # noqa: E402
from clean_arch.infrastructure.clean_worker import CleanSessionWorker  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--credentials", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--login-only", action="store_true")
    args = parser.parse_args()
    settings = SessionSettings(
        config_path=args.config,
        credentials_path=args.credentials,
        mode=SessionMode.LOGIN_ONLY if args.login_only else SessionMode.WORLD)
    service = SessionService(CleanSessionWorker())
    return service.run(settings, lambda event: print(event.text, flush=True))


if __name__ == "__main__":
    raise SystemExit(main())
