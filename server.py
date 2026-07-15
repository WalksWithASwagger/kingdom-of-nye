#!/usr/bin/env python3
"""Launch shim for the Kingdom of Nye v3 conductor.

Keeps the muscle-memory launch (`python3 server.py`) working: it re-execs into the
project virtualenv (which has aiohttp / whisper / python-osc) if it isn't already
running there, then hands off to conductor.app.

The real backend lives in conductor/ — see conductor/app.py.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENV_DIR = HERE / ".venv"
VENV_PY = VENV_DIR / "bin" / "python"


def _reexec_into_venv() -> None:
    if not VENV_PY.exists():
        return  # no venv yet; assume deps are on the current interpreter
    # A venv's python is a symlink to the base binary, so comparing executables is
    # unreliable — sys.prefix is what actually changes once we're inside the venv.
    if Path(sys.prefix).resolve() == VENV_DIR.resolve():
        return  # already inside it
    os.execv(str(VENV_PY), [str(VENV_PY), str(HERE / "server.py"), *sys.argv[1:]])


if __name__ == "__main__":
    _reexec_into_venv()
    sys.path.insert(0, str(HERE))
    from conductor.app import main
    main()
