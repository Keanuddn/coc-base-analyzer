#!/usr/bin/env python3
"""Compare wiki counts vs YOLO GT vs predictions for resource/army classes.

Does not invent Clash of Clans stats: wiki numbers come from
``data-pipeline/src/renderer/sprites/th_unlocks.yaml``. Default image is
synthetic_0003 (TH18). Run this after ``coc_yolo_v9`` finishes — do not run
Ultralytics predict on MPS while another train job holds the GPU.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import yaml

from model_utils import REPO_ROOT, ML_ROOT, model_class_names

UNLOCKS_PATH = (
    REPO_ROOT
    / "data-pipeline"
    / "src"
    / "renderer"
    / "sprites"
    / "th_unlocks.yaml"
)
DEFAULT_IMAGE = (
    REPO_ROOT
    / "data-pipeline"
    / "datasets"
    / "processed"
    / "synthetic_v1"
    / "th18"
    / "synthetic_0003.png"
)
DEFAULT_WEIGHTS = ML_ROOT / "runs" / "coc_yolo_v9" / "weights" / "best.pt"
FOCUS_CLASSES: tuple[str, ...] = (
    "goldmine",
    "elixircollector",
    "darkelixirdrill",
    "armycamp",
    "barracks",
    "darkbarracks",
    "laboratory",
    "spellfactory",
    "darkspellfactory",
    "workshop",
    "pethouse",
    "blacksmith",
    "herohall",
)


def load_unlocks(path: Path = UNLOCKS_PATH) -> dict:
    with path.open(encoding="utf-8") as fh:
        payload = yaml.safe_load(fh)
    buildings = payload.get("buildings", payload)
    if not isinstance(buildings, dict):
        raise ValueError(f"Unexpected unlocks shape in {path}")
    return buildings


def wiki_count(unlocks: dict, class_name: str, th_level: int) -> int | None:
    row = unlocks.get(class_name) or {}
    counts = row.get("count_by_th") or {}
    if th_level in counts:
        return int(counts[th_level])
    if str(th_level) in counts:
        return int(counts[str(th_level)])
    return None


def parse_yolo_class_counts(label_text: str, names: list[str]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for raw in label_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        class_id = int(line.split()[0])
        if 0 <= class_id < len(names):
            counts[names[class_id]] += 1
        else:
            counts[str(class_id)] += 1
    return counts


def load_gt_counts(label_path: Path, names: list[str]) -> Counter[str]:
    return parse_yolo_class_counts(label_path.read_text(encoding="utf-8"), names)


def pred_counts(buildings: list[dict]) -> Counter[str]:
    return Counter(str(b.get("class", b.get("class_id"))) for b in buildings)


def compare_focus(
    *,
    wiki: dict[str, int | None],
    gt: Counter[str],
    pred: Counter[str],
    focus: tuple[str, ...] = FOCUS_CLASSES,
) -> list[dict]:
    rows = []
    for name in focus:
        rows.append(
            {
                "class": name,
                "wiki": wiki.get(name),
                "gt": int(gt.get(name, 0)),
                "pred": int(pred.get(name, 0)),
            }
        )
    return rows


def format_table(rows: list[dict]) -> str:
    header = f"{'class':<20} {'wiki':>5} {'gt':>5} {'pred':>5}"
    lines = [header, "-" * len(header)]
    for row in rows:
        wiki = "—" if row["wiki"] is None else str(row["wiki"])
        lines.append(f"{row['class']:<20} {wiki:>5} {row['gt']:>5} {row['pred']:>5}")
    return "\n".join(lines)


def infer_th_from_path(image_path: Path) -> int:
    for part in image_path.parts:
        if part.startswith("th") and part[2:].isdigit():
            return int(part[2:])
    return 18


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Wiki vs GT vs pred counts for resource/army YOLO classes."
    )
    parser.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
    parser.add_argument("--labels", type=Path, default=None, help="YOLO .txt next to image if omitted")
    parser.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS)
    parser.add_argument("--th", type=int, default=None)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--overlay", type=Path, default=None)
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument(
        "--counts-only",
        action="store_true",
        help="Skip Ultralytics (CPU/GPU). Report wiki vs GT only.",
    )
    args = parser.parse_args(argv)

    if not args.image.is_file():
        print(f"Image not found: {args.image}", file=sys.stderr)
        return 1
    label_path = args.labels or args.image.with_suffix(".txt")
    if not label_path.is_file():
        print(f"Labels not found: {label_path}", file=sys.stderr)
        return 1

    names = model_class_names()
    th_level = args.th or infer_th_from_path(args.image)
    unlocks = load_unlocks()
    wiki = {name: wiki_count(unlocks, name, th_level) for name in FOCUS_CLASSES}
    gt = load_gt_counts(label_path, names)

    pred: Counter[str] = Counter()
    overlay_path = args.overlay
    if not args.counts_only:
        if not args.weights.is_file():
            print(
                f"Weights not found: {args.weights}\n"
                "Wait for coc_yolo_v9 or pass --weights. Use --counts-only for wiki vs GT.",
                file=sys.stderr,
            )
            return 1
        from infer import infer_ultralytics, DEFAULT_OVERLAY_FONT_SIZE, DEFAULT_OVERLAY_LINE_WIDTH

        if overlay_path is None:
            overlay_path = (
                ML_ROOT / "runs" / "coc_yolo_v9" / "eval" / "overlays" / f"{args.image.stem}.jpg"
            )
        result = infer_ultralytics(
            args.weights,
            args.image,
            conf=args.conf,
            iou=0.45,
            max_det=1000,
            overlay_path=overlay_path,
            overlay_line_width=DEFAULT_OVERLAY_LINE_WIDTH,
            overlay_font_size=DEFAULT_OVERLAY_FONT_SIZE,
        )
        pred = pred_counts(result["buildings"])
        print(f"Wrote overlay {overlay_path}")

    rows = compare_focus(wiki=wiki, gt=gt, pred=pred)
    report = {
        "image": str(args.image),
        "labels": str(label_path),
        "th": th_level,
        "weights": None if args.counts_only else str(args.weights),
        "conf": None if args.counts_only else args.conf,
        "rows": rows,
        "sources": "data-pipeline/src/renderer/sprites/th_unlocks.yaml",
    }
    print(format_table(rows))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {args.json_out}")
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
