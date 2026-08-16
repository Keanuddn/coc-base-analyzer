#!/usr/bin/env python3
"""Assemble YOLO-format train/val/test datasets from synthetic renders and real screenshots."""

from __future__ import annotations

import argparse
import json
import logging
import random
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml

from dataset.dedup import deduplicate_images_by_hash
from renderer.domain_randomization import DomainRandomizationConfig
from renderer.isometric_renderer import YOLO_CLASS_NAMES, IsometricRenderer
from renderer.demo_render import DEMO_PLACEMENTS

logger = logging.getLogger(__name__)

PIPELINE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PIPELINE_ROOT.parent

DEFAULT_DEMO_DIR = PIPELINE_ROOT / "datasets" / "processed" / "demo"
DEFAULT_SYNTHETIC_BULK_DIR = PIPELINE_ROOT / "datasets" / "processed" / "synthetic_v1"
DEFAULT_REGRESSION_DIR = REPO_ROOT / "ml" / "tests" / "regression_set"
DEFAULT_PSEUDO_LABELS_DIR = DEFAULT_REGRESSION_DIR / "labels"
DEFAULT_CLASSES_FILE = DEFAULT_REGRESSION_DIR / "classes.txt"
DEFAULT_OUTPUT = PIPELINE_ROOT / "datasets" / "processed" / "yolo_v1"

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
SplitName = Literal["train", "val", "test"]
OriginName = Literal["synthetic", "real"]


@dataclass(slots=True)
class DatasetSample:
    """One image destined for the YOLO dataset."""

    source_path: Path
    origin: OriginName
    town_hall_level: int | None
    has_labels: bool
    label_path: Path | None = None
    split: SplitName | None = None
    output_stem: str | None = None
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class BuildDatasetConfig:
    output_dir: Path
    train_ratio: float = 0.7
    val_ratio: float = 0.2
    test_ratio: float = 0.1
    seed: int = 42
    include_demo: bool = False
    include_regression: bool = False
    include_synthetic_bulk: bool = False
    include_pseudo_labels: bool = False
    manual_labels_only: bool = False
    user_screenshots_dir: Path | None = None
    demo_dir: Path = DEFAULT_DEMO_DIR
    synthetic_bulk_dir: Path = DEFAULT_SYNTHETIC_BULK_DIR
    regression_dir: Path = DEFAULT_REGRESSION_DIR
    pseudo_labels_dir: Path = DEFAULT_PSEUDO_LABELS_DIR
    approved_reviews_path: Path | None = None
    synthetic_variant_count: int = 8
    render_synthetic_variants: bool = True


@dataclass(slots=True)
class BuildDatasetResult:
    output_dir: Path
    report_path: Path
    data_yaml_path: Path
    summary: dict[str, Any]


def infer_town_hall_level(path: Path) -> int | None:
    """Infer TH level from ``th15/`` parent folder or ``th15_`` filename prefix."""
    for part in path.parts:
        lower = part.lower()
        if lower.startswith("th") and lower[2:].isdigit():
            return int(lower[2:])
    stem = path.stem.lower()
    if stem.startswith("th") and len(stem) >= 4 and stem[2:4].isdigit():
        return int(stem[2:4])
    return None


def _collect_labeled_pairs(directory: Path, *, origin: OriginName, default_th: int | None) -> list[DatasetSample]:
    samples: list[DatasetSample] = []
    if not directory.is_dir():
        return samples

    for image_path in sorted(directory.rglob("*")):
        if image_path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        label_path = image_path.with_suffix(".txt")
        has_labels = label_path.is_file()
        th = infer_town_hall_level(image_path) or default_th
        samples.append(
            DatasetSample(
                source_path=image_path,
                origin=origin,
                town_hall_level=th,
                has_labels=has_labels,
                label_path=label_path if has_labels else None,
            )
        )
    return samples


def collect_synthetic_samples(config: BuildDatasetConfig) -> list[DatasetSample]:
    """Collect demo PNG+txt and optionally render extra synthetic variants."""
    samples = _collect_labeled_pairs(config.demo_dir, origin="synthetic", default_th=15)

    if not config.render_synthetic_variants or config.synthetic_variant_count <= 0:
        return samples

    if not IsometricRenderer.sprites_available():
        logger.warning(
            "Sprites unavailable — skipping extra synthetic renders "
            "(only existing demo files used)."
        )
        return samples

    staging = config.output_dir / "_staging" / "synthetic"
    staging.mkdir(parents=True, exist_ok=True)
    renderer = IsometricRenderer(use_placeholders=True)

    for variant_idx in range(config.synthetic_variant_count):
        seed = config.seed + variant_idx
        out_png = staging / f"synthetic_th15_variant_{variant_idx:03d}.png"
        if out_png.is_file() and out_png.with_suffix(".txt").is_file():
            samples.append(
                DatasetSample(
                    source_path=out_png,
                    origin="synthetic",
                    town_hall_level=15,
                    has_labels=True,
                    label_path=out_png.with_suffix(".txt"),
                )
            )
            continue

        dr_cfg = DomainRandomizationConfig(seed=seed)
        result = renderer.render_to_files(
            DEMO_PLACEMENTS,
            out_png,
            domain_randomization=dr_cfg,
            seed=seed,
        )
        if result.output_path and result.label_path:
            samples.append(
                DatasetSample(
                    source_path=result.output_path,
                    origin="synthetic",
                    town_hall_level=15,
                    has_labels=True,
                    label_path=result.label_path,
                )
            )

    return samples


def collect_synthetic_bulk_samples(config: BuildDatasetConfig) -> list[DatasetSample]:
    """Collect pre-rendered bulk synthetics (``synthetic_v1/th15|th16/*.png``)."""
    return _collect_labeled_pairs(config.synthetic_bulk_dir, origin="synthetic", default_th=None)


def _load_approved_reviews(path: Path | None) -> set[str] | None:
    """Load approved image paths from label review JSON (None = no filter)."""
    if path is None or not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        entry["path"]
        for entry in payload.get("reviews", [])
        if entry.get("status") == "approved" and entry.get("path")
    }


def _load_active_class_names(classes_file: Path = DEFAULT_CLASSES_FILE) -> list[str]:
    """Load active class names from regression-set classes.txt (labelImg predefined list)."""
    if classes_file.is_file():
        return [
            line.strip()
            for line in classes_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    return [name for name in YOLO_CLASS_NAMES if name not in {"kingpad", "queenpad", "rcpad", "wardenpad"}]


def labels_use_model_indices(lines: list[str], active_names: list[str]) -> bool:
    """True if labels already store keremberke 0..15 ids (FastAPI canvas labeler).

    labelImg wrote compact active-class indices (0..len(active)-1). The browser
    labeler writes model indices, including 14=wizztower and 15=xbow, which are
    out of range for the 12-name classes.txt list and must not be remapped.
    """
    for line in lines:
        parts = line.strip().split()
        if len(parts) < 5:
            continue
        if int(parts[0]) >= len(active_names):
            return True
    return False


def remap_active_class_indices(lines: list[str], active_names: list[str]) -> list[str]:
    """Map labelImg active-class indices (0..len(active)-1) to keremberke model indices.

    Files that already use model indices are passed through unchanged (aside from
    dropping malformed / out-of-range lines).
    """
    remapped: list[str] = []
    if labels_use_model_indices(lines, active_names):
        for line in lines:
            parts = line.strip().split()
            if len(parts) < 5:
                continue
            idx = int(parts[0])
            if idx < 0 or idx >= len(YOLO_CLASS_NAMES):
                logger.warning("Skipping label line with out-of-range class index %d: %s", idx, line)
                continue
            remapped.append(" ".join(parts))
        return remapped

    for line in lines:
        parts = line.strip().split()
        if len(parts) < 5:
            continue
        active_idx = int(parts[0])
        if active_idx < 0 or active_idx >= len(active_names):
            logger.warning("Skipping label line with out-of-range class index %d: %s", active_idx, line)
            continue
        model_idx = YOLO_CLASS_NAMES.index(active_names[active_idx])
        parts[0] = str(model_idx)
        remapped.append(" ".join(parts))
    return remapped


def _load_pseudo_label_index(pseudo_labels_dir: Path) -> dict[str, bool]:
    """Load pseudo-label metadata index (image rel path → pseudo_label flag)."""
    meta_path = pseudo_labels_dir / "_pseudo_label_metadata.json"
    if not meta_path.is_file():
        return {}
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    return {
        key: bool(entry.get("pseudo_label"))
        for key, entry in payload.get("labels", {}).items()
    }


def resolve_regression_label_path(
    image_path: Path,
    regression_dir: Path,
    *,
    include_pseudo_labels: bool,
    manual_labels_only: bool,
    pseudo_labels_dir: Path,
) -> tuple[Path | None, list[str]]:
    """Resolve YOLO label sidecar: alongside image, or under labels/ for manual/pseudo labels."""
    notes: list[str] = []
    sidecar = image_path.with_suffix(".txt")
    if sidecar.is_file():
        if manual_labels_only:
            notes.append("manual_label")
        return sidecar, notes

    use_labels_dir = include_pseudo_labels or manual_labels_only
    if not use_labels_dir:
        notes.append("manual_labeling_required")
        return None, notes

    try:
        rel = image_path.relative_to(regression_dir)
    except ValueError:
        notes.append("manual_labeling_required")
        return None, notes

    labels_path = pseudo_labels_dir / rel.with_suffix(".txt")
    if labels_path.is_file():
        if manual_labels_only:
            notes.append("manual_label")
        else:
            notes.append("pseudo_label")
            notes.append("manual_review_recommended")
        return labels_path, notes

    notes.append("manual_labeling_required")
    return None, notes


def collect_real_samples(config: BuildDatasetConfig) -> list[DatasetSample]:
    """Collect regression-set and optional user screenshots (typically unlabeled)."""
    samples: list[DatasetSample] = []
    pseudo_index = (
        _load_pseudo_label_index(config.pseudo_labels_dir)
        if config.include_pseudo_labels and not config.manual_labels_only
        else {}
    )

    approved_paths = _load_approved_reviews(config.approved_reviews_path)

    if config.include_regression and config.regression_dir.is_dir():
        for image_path in sorted(config.regression_dir.rglob("*")):
            if image_path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            if any(
                part in {"_rejected", "_pseudo_backup"} or part.startswith("labels_backup")
                for part in image_path.parts
            ):
                continue
            if "labels" in image_path.parts and image_path.parent.name == "labels":
                continue
            if approved_paths is not None:
                try:
                    rel_key = str(image_path.relative_to(config.regression_dir))
                except ValueError:
                    continue
                if rel_key not in approved_paths:
                    continue
            label_path, notes = resolve_regression_label_path(
                image_path,
                config.regression_dir,
                include_pseudo_labels=config.include_pseudo_labels,
                manual_labels_only=config.manual_labels_only,
                pseudo_labels_dir=config.regression_dir / "labels",
            )
            has_labels = label_path is not None
            if has_labels:
                try:
                    rel_key = str(image_path.relative_to(config.regression_dir))
                    if pseudo_index.get(rel_key):
                        if "pseudo_label" not in notes:
                            notes.append("pseudo_label")
                except ValueError:
                    pass
            samples.append(
                DatasetSample(
                    source_path=image_path,
                    origin="real",
                    town_hall_level=infer_town_hall_level(image_path),
                    has_labels=has_labels,
                    label_path=label_path,
                    notes=notes,
                )
            )

    if config.user_screenshots_dir and config.user_screenshots_dir.is_dir():
        samples.extend(
            _collect_labeled_pairs(
                config.user_screenshots_dir,
                origin="real",
                default_th=None,
            )
        )
        for sample in samples:
            if sample.origin == "real" and not sample.has_labels:
                sample.notes.append("manual_labeling_required")

    samples.sort(key=lambda s: (0 if s.has_labels else 1, str(s.source_path)))
    unique_paths, dupes = deduplicate_images_by_hash([s.source_path for s in samples])
    if dupes:
        logger.info("Removed %d duplicate real screenshot(s) by content hash", len(dupes))
    deduped = {p.resolve(): p for p in unique_paths}
    return [s for s in samples if s.source_path.resolve() in deduped]


def assign_splits(
    samples: list[DatasetSample],
    *,
    train_ratio: float,
    val_ratio: float,
    test_ratio: float,
    seed: int,
) -> None:
    """Assign train/val/test splits, stratified by TH where possible."""
    total_ratio = train_ratio + val_ratio + test_ratio
    if abs(total_ratio - 1.0) > 1e-6:
        raise ValueError(f"Split ratios must sum to 1.0, got {total_ratio}")

    rng = random.Random(seed)

    labeled = [s for s in samples if s.has_labels]
    unlabeled = [s for s in samples if not s.has_labels]

    by_th: dict[int | None, list[DatasetSample]] = {}
    for sample in labeled:
        by_th.setdefault(sample.town_hall_level, []).append(sample)

    for group in by_th.values():
        rng.shuffle(group)
        n = len(group)
        if n == 0:
            continue
        n_train = max(1, int(round(n * train_ratio))) if n >= 3 else (1 if n >= 1 else 0)
        n_val = max(0, int(round(n * val_ratio))) if n >= 3 else (1 if n >= 2 else 0)
        n_test = n - n_train - n_val
        if n_test < 0:
            n_test = 0
            n_val = max(0, n - n_train)
        if n == 1:
            group[0].split = "train"
        elif n == 2:
            group[0].split = "train"
            group[1].split = "val"
        else:
            for idx, sample in enumerate(group):
                if idx < n_train:
                    sample.split = "train"
                elif idx < n_train + n_val:
                    sample.split = "val"
                else:
                    sample.split = "test"

    rng.shuffle(unlabeled)
    for idx, sample in enumerate(unlabeled):
        sample.split = "val" if idx % 2 == 0 else "test"
        sample.notes.append("included_unlabeled_for_inference_only")


def _safe_stem(path: Path, origin: OriginName, index: int) -> str:
    stem = path.stem.replace(" ", "_")
    return f"{origin}_{stem}_{index:04d}"


def materialize_yolo_dataset(
    samples: list[DatasetSample],
    output_dir: Path,
    *,
    remap_manual_labels: bool = False,
    active_class_names: list[str] | None = None,
) -> dict[str, Any]:
    """Copy images and labels into YOLO directory layout."""
    output_dir.mkdir(parents=True, exist_ok=True)

    copied: list[dict[str, Any]] = []
    unlabeled_copied: list[dict[str, Any]] = []

    for idx, sample in enumerate(samples):
        if sample.split is None:
            continue

        stem = _safe_stem(sample.source_path, sample.origin, idx)
        sample.output_stem = stem

        if sample.has_labels:
            img_dir = output_dir / sample.split / "images"
            lbl_dir = output_dir / sample.split / "labels"
            img_dir.mkdir(parents=True, exist_ok=True)
            lbl_dir.mkdir(parents=True, exist_ok=True)
            dest_img = img_dir / f"{stem}{sample.source_path.suffix.lower()}"
            dest_lbl = lbl_dir / f"{stem}.txt"
            shutil.copy2(sample.source_path, dest_img)
            if sample.label_path and sample.label_path.is_file():
                if remap_manual_labels and "manual_label" in sample.notes:
                    lines = sample.label_path.read_text(encoding="utf-8").splitlines()
                    active_names = active_class_names or _load_active_class_names()
                    remapped = remap_active_class_indices(lines, active_names)
                    dest_lbl.write_text("\n".join(remapped) + ("\n" if remapped else ""), encoding="utf-8")
                else:
                    shutil.copy2(sample.label_path, dest_lbl)
            copied.append(
                {
                    "stem": stem,
                    "split": sample.split,
                    "origin": sample.origin,
                    "town_hall_level": sample.town_hall_level,
                    "image": str(dest_img.relative_to(output_dir)),
                    "label": str(dest_lbl.relative_to(output_dir)),
                    "has_labels": True,
                }
            )
        else:
            unlabeled_split = sample.split
            img_dir = output_dir / unlabeled_split / "images_unlabeled"
            img_dir.mkdir(parents=True, exist_ok=True)
            dest_img = img_dir / f"{stem}{sample.source_path.suffix.lower()}"
            shutil.copy2(sample.source_path, dest_img)
            unlabeled_copied.append(
                {
                    "stem": stem,
                    "split": unlabeled_split,
                    "origin": sample.origin,
                    "town_hall_level": sample.town_hall_level,
                    "image": str(dest_img.relative_to(output_dir)),
                    "has_labels": False,
                    "notes": sample.notes,
                }
            )

    return {"labeled": copied, "unlabeled": unlabeled_copied}


def write_data_yaml(output_dir: Path) -> Path:
    """Write Ultralytics-compatible ``data.yaml``."""
    names = {idx: name for idx, name in enumerate(YOLO_CLASS_NAMES)}
    payload = {
        "path": str(output_dir.resolve()),
        "train": "train/images",
        "val": "val/images",
        "test": "test/images",
        "nc": len(YOLO_CLASS_NAMES),
        "names": names,
    }
    path = output_dir / "data.yaml"
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(payload, fh, sort_keys=False, default_flow_style=False)
    return path


def build_summary(samples: list[DatasetSample], materialized: dict[str, Any]) -> dict[str, Any]:
    """Build dataset report summary with TH balance and real/synthetic counts."""
    th_balance: dict[str, dict[str, int]] = {}
    for sample in samples:
        if sample.split is None:
            continue
        th_key = f"TH{sample.town_hall_level}" if sample.town_hall_level else "unknown"
        th_balance.setdefault(th_key, {"train": 0, "val": 0, "test": 0, "total": 0})
        th_balance[th_key][sample.split] += 1
        th_balance[th_key]["total"] += 1

    origin_split: dict[str, dict[str, int]] = {
        "synthetic": {"train": 0, "val": 0, "test": 0, "total": 0},
        "real": {"train": 0, "val": 0, "test": 0, "total": 0},
    }
    for sample in samples:
        if sample.split is None:
            continue
        origin_split[sample.origin][sample.split] += 1
        origin_split[sample.origin]["total"] += 1

    labeled = [s for s in samples if s.has_labels and s.split]
    unlabeled = [s for s in samples if not s.has_labels and s.split]

    return {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "totals": {
            "samples": len(samples),
            "labeled": len(labeled),
            "unlabeled": len(unlabeled),
            "synthetic": sum(1 for s in samples if s.origin == "synthetic"),
            "real": sum(1 for s in samples if s.origin == "real"),
        },
        "real_vs_synthetic_ratio": {
            "synthetic": sum(1 for s in samples if s.origin == "synthetic"),
            "real": sum(1 for s in samples if s.origin == "real"),
            "ratio_real_to_synthetic": round(
                sum(1 for s in samples if s.origin == "real")
                / max(1, sum(1 for s in samples if s.origin == "synthetic")),
                4,
            ),
        },
        "town_hall_balance": th_balance,
        "origin_by_split": origin_split,
        "unlabeled_real_images": {
            "count": len(unlabeled),
            "warning": (
                "Real regression screenshots have no YOLO labels yet. "
                "They are placed under {split}/images_unlabeled/ for inference-only "
                "validation. Manual labeling or pseudo-labels required before training."
            ),
            "items": [
                {
                    "source": str(s.source_path),
                    "split": s.split,
                    "town_hall_level": s.town_hall_level,
                    "notes": s.notes,
                }
                for s in unlabeled
            ],
        },
        "materialized_files": materialized,
        "labeling_todo": [
            "Label real screenshots in ml/tests/regression_set/ (YOLO .txt sidecars)",
            "Manual labeling guide: ml/docs/MANUAL_LABELING.md (labelImg + classes.txt)",
            "Pseudo-labels: ml/src/pseudo_label.py → ml/tests/regression_set/labels/ (review manually)",
        ],
    }


def write_dataset_report(output_dir: Path, summary: dict[str, Any]) -> tuple[Path, Path]:
    """Write JSON and Markdown dataset reports."""
    json_path = output_dir / "dataset_report.json"
    json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    md_path = output_dir / "dataset_report.md"
    totals = summary["totals"]
    ratio = summary["real_vs_synthetic_ratio"]
    lines = [
        "# Dataset Report",
        "",
        f"Generated: {summary['generated_at']}",
        "",
        "## Totals",
        "",
        f"- Samples: {totals['samples']}",
        f"- Labeled: {totals['labeled']}",
        f"- Unlabeled: {totals['unlabeled']}",
        f"- Synthetic: {totals['synthetic']}",
        f"- Real: {totals['real']}",
        f"- Real:Synthetic ratio: {ratio['real']}:{ratio['synthetic']} "
        f"({ratio['ratio_real_to_synthetic']:.4f} real per synthetic)",
        "",
        "## Town Hall balance",
        "",
        "| TH | train | val | test | total |",
        "|----|-------|-----|------|-------|",
    ]
    for th, counts in sorted(summary["town_hall_balance"].items()):
        lines.append(
            f"| {th} | {counts['train']} | {counts['val']} | {counts['test']} | {counts['total']} |"
        )
    lines.extend(
        [
            "",
            "## Unlabeled real images",
            "",
            summary["unlabeled_real_images"]["warning"],
            "",
            f"Count: {summary['unlabeled_real_images']['count']}",
            "",
            "## Labeling TODO",
            "",
        ]
    )
    for item in summary["labeling_todo"]:
        lines.append(f"- {item}")
    lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def build_yolo_dataset(config: BuildDatasetConfig) -> BuildDatasetResult:
    """Assemble a YOLO dataset from configured sources."""
    samples: list[DatasetSample] = []

    if config.include_demo:
        samples.extend(collect_synthetic_samples(config))
    if config.include_synthetic_bulk:
        samples.extend(collect_synthetic_bulk_samples(config))
    if config.include_regression or config.user_screenshots_dir:
        samples.extend(collect_real_samples(config))

    if not samples:
        raise ValueError(
            "No samples collected — enable --include-demo, --include-synthetic-bulk, "
            "and/or --include-regression"
        )

    assign_splits(
        samples,
        train_ratio=config.train_ratio,
        val_ratio=config.val_ratio,
        test_ratio=config.test_ratio,
        seed=config.seed,
    )

    config.output_dir.mkdir(parents=True, exist_ok=True)
    for split in ("train", "val", "test"):
        for sub in ("images", "labels", "images_unlabeled"):
            target = config.output_dir / split / sub
            if target.is_dir():
                shutil.rmtree(target)
    active_names = _load_active_class_names() if config.manual_labels_only else None
    materialized = materialize_yolo_dataset(
        samples,
        config.output_dir,
        remap_manual_labels=config.manual_labels_only,
        active_class_names=active_names,
    )
    data_yaml_path = write_data_yaml(config.output_dir)
    summary = build_summary(samples, materialized)
    report_path, _ = write_dataset_report(config.output_dir, summary)

    staging = config.output_dir / "_staging"
    if staging.is_dir():
        shutil.rmtree(staging, ignore_errors=True)

    return BuildDatasetResult(
        output_dir=config.output_dir,
        report_path=report_path,
        data_yaml_path=data_yaml_path,
        summary=summary,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Assemble YOLO train/val/test dataset from synthetic renders and real screenshots."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output directory (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument("--include-demo", action="store_true", help="Include synthetic demo renders")
    parser.add_argument(
        "--include-synthetic-bulk",
        action="store_true",
        help="Include bulk synthetic renders from datasets/processed/synthetic_v1/",
    )
    parser.add_argument(
        "--synthetic-bulk-dir",
        type=Path,
        default=DEFAULT_SYNTHETIC_BULK_DIR,
        help="Directory with bulk synthetic PNG+txt (default: synthetic_v1)",
    )
    parser.add_argument(
        "--include-regression",
        action="store_true",
        help="Include real screenshots from ml/tests/regression_set/",
    )
    parser.add_argument(
        "--include-pseudo-labels",
        action="store_true",
        help="Use pseudo-labels from ml/tests/regression_set/labels/ for real images",
    )
    parser.add_argument(
        "--manual-labels-only",
        action="store_true",
        help=(
            "Use only existing manual .txt labels under regression_set/labels/ "
            "(ignore pseudo-label metadata; remap active class indices from classes.txt)"
        ),
    )
    parser.add_argument(
        "--user-screenshots",
        type=Path,
        default=None,
        help="Optional directory of user-provided screenshots",
    )
    parser.add_argument("--train-ratio", type=float, default=0.7)
    parser.add_argument("--val-ratio", type=float, default=0.2)
    parser.add_argument("--test-ratio", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--synthetic-variants",
        type=int,
        default=8,
        help="Extra synthetic renders (when sprites available)",
    )
    parser.add_argument(
        "--no-render-variants",
        action="store_true",
        help="Skip rendering extra synthetic variants",
    )
    parser.add_argument(
        "--demo-dir",
        type=Path,
        default=DEFAULT_DEMO_DIR,
        help="Directory with demo synthetic PNG+txt",
    )
    parser.add_argument(
        "--regression-dir",
        type=Path,
        default=DEFAULT_REGRESSION_DIR,
        help="Regression screenshot root",
    )
    parser.add_argument(
        "--approved-reviews",
        type=Path,
        default=None,
        help="Only include regression images approved in label review JSON",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    if (
        not args.include_demo
        and not args.include_regression
        and not args.user_screenshots
        and not args.include_synthetic_bulk
    ):
        parser.error(
            "Specify at least one of --include-demo, --include-synthetic-bulk, "
            "--include-regression, --user-screenshots"
        )
    if args.manual_labels_only and args.include_pseudo_labels:
        parser.error("Use either --manual-labels-only or --include-pseudo-labels, not both")

    config = BuildDatasetConfig(
        output_dir=args.output,
        train_ratio=args.train_ratio,
        val_ratio=args.val_ratio,
        test_ratio=args.test_ratio,
        seed=args.seed,
        include_demo=args.include_demo,
        include_regression=args.include_regression,
        include_synthetic_bulk=args.include_synthetic_bulk,
        include_pseudo_labels=args.include_pseudo_labels,
        manual_labels_only=args.manual_labels_only,
        user_screenshots_dir=args.user_screenshots,
        demo_dir=args.demo_dir,
        synthetic_bulk_dir=args.synthetic_bulk_dir,
        regression_dir=args.regression_dir,
        pseudo_labels_dir=args.regression_dir / "labels",
        approved_reviews_path=args.approved_reviews,
        synthetic_variant_count=args.synthetic_variants,
        render_synthetic_variants=not args.no_render_variants,
    )

    try:
        result = build_yolo_dataset(config)
    except ValueError as exc:
        logging.error("%s", exc)
        return 1

    totals = result.summary["totals"]
    logging.info(
        "Dataset written to %s — %d labeled, %d unlabeled (%d synthetic, %d real)",
        result.output_dir,
        totals["labeled"],
        totals["unlabeled"],
        totals["synthetic"],
        totals["real"],
    )
    logging.info("Report: %s", result.report_path)
    logging.info("data.yaml: %s", result.data_yaml_path)
    print(json.dumps(result.summary["totals"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
