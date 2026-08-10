#!/usr/bin/env python3
"""Patch labelImg scroll/zoom setValue float bug (PyQt5 on Python 3.12+).

QAbstractSlider.setValue requires int; labelImg passes float from wheel deltas.
Idempotent — safe to run after every pip install or at launcher startup.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPLACEMENTS: list[tuple[str, str]] = [
    (
        "bar.setValue(bar.value() + bar.singleStep() * units)",
        "bar.setValue(int(bar.value() + bar.singleStep() * units))",
    ),
    (
        "h_bar.setValue(new_h_bar_value)",
        "h_bar.setValue(int(new_h_bar_value))",
    ),
    (
        "v_bar.setValue(new_v_bar_value)",
        "v_bar.setValue(int(new_v_bar_value))",
    ),
    (
        "self.zoom_widget.setValue(value)",
        "self.zoom_widget.setValue(int(value))",
    ),
]

MARKER = "# patched: labelImg setValue int cast (coc-base-analyzer)"


def find_labelimg_py(venv_root: Path) -> Path | None:
    lib = venv_root / "lib"
    if not lib.is_dir():
        return None
    for py_dir in lib.glob("python*/site-packages/labelImg/labelImg.py"):
        return py_dir
    return None


def patch_file(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if MARKER in text:
        return False

    original = text
    for old, new in REPLACEMENTS:
        if old not in text:
            if new in text:
                continue
            print(f"patch_labelimg: pattern not found in {path}: {old!r}", file=sys.stderr)
            sys.exit(1)
        text = text.replace(old, new, 1)

    if text == original:
        return False

    if not text.lstrip().startswith("#!/"):
        text = f"{MARKER}\n{text}"
    else:
        first_newline = text.index("\n")
        text = text[: first_newline + 1] + MARKER + "\n" + text[first_newline + 1 :]

    path.write_text(text, encoding="utf-8")
    return True


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <venv-root>", file=sys.stderr)
        return 2

    venv_root = Path(sys.argv[1]).resolve()
    target = find_labelimg_py(venv_root)
    if target is None:
        print(f"patch_labelimg: labelImg.py not found under {venv_root}", file=sys.stderr)
        return 1

    if patch_file(target):
        print(f"Patched {target}")
    else:
        print(f"Already patched: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
