#!/usr/bin/env python3
"""Entry point for the visual-control skill.

Usage::

    python scripts/visual_control.py observe --with-cursor --with-windows
    python scripts/visual_control.py click --at 640,360
    python scripts/visual_control.py type --text "hello"
    python scripts/visual_control.py hotkey --keys ctrl+shift+s
    python scripts/visual_control.py scroll --direction down --amount 4
    python scripts/visual_control.py drag --start 100,100 --to 500,400

Always prints one JSON object on stdout.  Exit code 0 = ok, 1 = failed,
2 = bad arguments.  Add ``--dry-run`` anywhere before the subcommand to
validate the plan without controlling the real mouse/keyboard.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Emit UTF-8 and never crash on legacy consoles (Chinese Windows cp936, etc.).
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from visual_control.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
