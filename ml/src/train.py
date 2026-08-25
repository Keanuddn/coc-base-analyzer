#!/usr/bin/env python3
"""Fine-tune YOLOv8/YOLO11 on the CoC dataset using Ultralytics."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import yaml

from model_utils import REPO_ROOT, ML_ROOT

DEFAULT_CONFIG = ML_ROOT / "configs" / "train_config.yaml"


def load_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def resolve_path(path_str: str) -> Path:
    path = Path(path_str)
    return path if path.is_absolute() else REPO_ROOT / path


def pick_device(requested: str) -> str | int:
    if requested != "auto":
        return requested
    try:
        import torch

        if torch.cuda.is_available():
            return 0
        if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
            return "mps"
        return "cpu"
    except ImportError:
        return "cpu"


def train(
    config_path: Path,
    *,
    smoke_test: bool = False,
    data_yaml: Path | None = None,
    resume: str | None = None,
    name: str | None = None,
    epochs: int | None = None,
    patience: int | None = None,
) -> dict:
    from ultralytics import YOLO

    cfg = load_config(config_path)
    train_cfg = cfg["training"]
    data_path = data_yaml or resolve_path(cfg["data"]["dataset_yaml"])

    if not data_path.is_file():
        raise FileNotFoundError(
            f"Dataset YAML not found: {data_path}\n"
            "Rebuild with: cd data-pipeline && python -m dataset.build_dataset "
            "--output datasets/processed/yolo_v1 --include-demo --include-regression "
            "--include-pseudo-labels"
        )

    n_epochs = epochs if epochs is not None else train_cfg["epochs"]
    batch = train_cfg["batch"]
    imgsz = train_cfg["imgsz"]
    if smoke_test:
        smoke = train_cfg.get("smoke_test", {})
        n_epochs = smoke.get("epochs", 2)
        batch = smoke.get("batch", 4)
        imgsz = smoke.get("imgsz", imgsz)
        logging.warning("Smoke test mode: epochs=%d batch=%d", n_epochs, batch)

    device = pick_device(train_cfg.get("device", "auto"))
    project = resolve_path(train_cfg["project"])
    run_name = name or train_cfg["name"]
    if smoke_test:
        run_name = f"{run_name}_smoke"

    model_source = resume or cfg["model"]["base"]
    model = YOLO(model_source)

    results = model.train(
        data=str(data_path),
        epochs=n_epochs,
        batch=batch,
        imgsz=imgsz,
        patience=patience if patience is not None else train_cfg.get("patience", 10),
        device=device,
        workers=train_cfg.get("workers", 4),
        project=str(project),
        name=run_name,
        seed=train_cfg.get("seed", 42),
        exist_ok=True,
        cache=train_cfg.get("cache", False),
        plots=train_cfg.get("plots", True),
        save=True,
        save_period=1,  # epochN.pt so a dropped connection can continue from last finished epoch
        resume=False,  # --resume CLI loads weights as start; never Ultralytics resume=True
    )

    best_weights = Path(results.save_dir) / "weights" / "best.pt"
    summary = {
        "smoke_test": smoke_test,
        "epochs": n_epochs,
        "batch": batch,
        "imgsz": imgsz,
        "device": str(device),
        "data_yaml": str(data_path),
        "save_dir": str(results.save_dir),
        "best_weights": str(best_weights) if best_weights.is_file() else None,
    }
    report_path = Path(results.save_dir) / "train_summary.json"
    report_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fine-tune YOLO on CoC dataset (Ultralytics).")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--data", type=Path, default=None, help="Override dataset data.yaml")
    parser.add_argument("--name", type=str, default=None, help="Override Ultralytics run name")
    parser.add_argument("--epochs", type=int, default=None, help="Override training epochs")
    parser.add_argument("--patience", type=int, default=None, help="Override early-stopping patience")
    parser.add_argument("--smoke-test", action="store_true", help="Run 1-3 epoch CPU-friendly smoke test")
    parser.add_argument("--resume", type=str, default=None, help="Resume from checkpoint .pt")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")

    try:
        summary = train(
            args.config,
            smoke_test=args.smoke_test,
            data_yaml=args.data,
            resume=args.resume,
            name=args.name,
            epochs=args.epochs,
            patience=args.patience,
        )
    except FileNotFoundError as exc:
        logging.error("%s", exc)
        return 1

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
