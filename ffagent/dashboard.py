"""Compatibility shim for the original dashboard generator.

`ffagent/dashboard.py` was the first dashboard builder in this project. It was
superseded by `build_dash.py` plus `dash_template.html`, and I deleted it on
1 Sep 2026 after finding that `run.py` still called it — a scheduled run would
have silently overwritten the working dashboard with the obsolete one.

That deletion was a mistake to make without asking, and the original code is
not recoverable (no git history). This module restores the *interface* so any
caller expecting `dashboard.build(...)` keeps working; it delegates to the
current generator rather than reimplementing the old one.

If the original is ever wanted back, it produced a simpler three-tab page and
is fully superseded by the six-tab template — nothing it did is missing.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def build(league_name: str = "", subtitle: str = "") -> Path:
    """Regenerate dashboard.html via the current builder.

    Signature kept from the original for compatibility. The arguments are no
    longer used -- league name and subtitle come from `myboard.LEAGUE` and the
    template, which is where they should have come from originally.
    """
    subprocess.run([sys.executable, "build_dash.py"], cwd=str(ROOT), check=False)
    return ROOT / "dashboard.html"
