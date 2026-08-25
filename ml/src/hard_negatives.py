"""Export background and confusion crops for YOLO (empty or relabeled)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from PIL import Image

from model_utils import model_class_names

DEFAULT_SELECTION = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "regression_set"
    / "hard_negatives"
    / "selection.yaml"
)


def load_selection(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        payload = yaml.safe_load(fh) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Expected mapping in {path}")
    return payload


def _clip_box(xyxy: list[float], width: int, height: int) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = (float(v) for v in xyxy)
    left = max(0, int(round(min(x1, x2))))
    top = max(0, int(round(min(y1, y2))))
    right = min(width, int(round(max(x1, x2))))
    bottom = min(height, int(round(max(y1, y2))))
    if right <= left or bottom <= top:
        raise ValueError(f"Empty crop {xyxy} on {width}x{height}")
    return left, top, right, bottom


def _padded(xyxy: list[float], pad: int, width: int, height: int) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = (float(v) for v in xyxy)
    return _clip_box([x1 - pad, y1 - pad, x2 + pad, y2 + pad], width, height)


def box_to_yolo(
    box_xyxy: list[float],
    crop: tuple[int, int, int, int],
) -> tuple[float, float, float, float]:
    left, top, right, bottom = crop
    width = right - left
    height = bottom - top
    x1, y1, x2, y2 = (float(v) for v in box_xyxy)
    cx1 = min(max(x1, left), right)
    cy1 = min(max(y1, top), bottom)
    cx2 = min(max(x2, left), right)
    cy2 = min(max(y2, top), bottom)
    if cx2 <= cx1 or cy2 <= cy1:
        raise ValueError("Box does not intersect crop")
    return (
        ((cx1 + cx2) / 2 - left) / width,
        ((cy1 + cy2) / 2 - top) / height,
        (cx2 - cx1) / width,
        (cy2 - cy1) / height,
    )


def export_from_selection(
    *,
    selection_path: Path,
    out_dir: Path | None = None,
    class_names: list[str] | None = None,
) -> list[Path]:
    selection = load_selection(selection_path)
    source = (selection_path.parent / str(selection["source_image"])).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    dest = out_dir or selection_path.parent
    dest.mkdir(parents=True, exist_ok=True)
    names = class_names if class_names is not None else model_class_names()
    image = Image.open(source).convert("RGB")
    stem_prefix = source.stem + "_hn"
    written: list[Path] = []

    for row in selection.get("background") or []:
        crop = _clip_box(row["xyxy"], image.width, image.height)
        png = dest / f"{stem_prefix}_{row['id']}.png"
        image.crop(crop).save(png)
        png.with_suffix(".txt").write_text("", encoding="utf-8")
        written.append(png)

    for row in selection.get("relabel") or []:
        class_name = str(row["class"])
        if class_name not in names:
            raise ValueError(f"Unknown class {class_name}")
        pad = int(row.get("pad") or 0)
        crop = _padded(row["xyxy"], pad, image.width, image.height)
        png = dest / f"{stem_prefix}_{row['id']}.png"
        image.crop(crop).save(png)
        cx, cy, bw, bh = box_to_yolo(row["xyxy"], crop)
        line = f"{names.index(class_name)} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}\n"
        png.with_suffix(".txt").write_text(line, encoding="utf-8")
        written.append(png)

    return written


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Export hard-negative crops from selection.yaml")
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    paths = export_from_selection(selection_path=args.selection, out_dir=args.out)
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
