#!/usr/bin/env python3
"""Deprecated — use manual_label_server.py (FastAPI canvas labeler).

This stub remains so old bookmarks/scripts still work.
"""

from __future__ import annotations

import runpy
from pathlib import Path

if __name__ == "__main__":
    server = Path(__file__).resolve().with_name("manual_label_server.py")
    runpy.run_path(str(server), run_name="__main__")
