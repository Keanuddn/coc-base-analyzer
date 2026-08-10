"""Shared model loading utilities for keremberke YOLOv5 baseline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ML_ROOT = REPO_ROOT / "ml"
CONFIG_DIR = ML_ROOT / "configs"
DEFAULT_MODEL_ID = "keremberke/yolov5m-clash-of-clans"


def _patch_huggingface_hub_for_yolov5() -> None:
    """yolov5 imports huggingface_hub.utils._errors (removed in hub 1.0+)."""
    import sys
    import types

    if "huggingface_hub.utils._errors" in sys.modules:
        return
    try:
        import huggingface_hub.utils._errors  # noqa: F401
        return
    except ModuleNotFoundError:
        pass

    from huggingface_hub.errors import RepositoryNotFoundError

    mod = types.ModuleType("huggingface_hub.utils._errors")
    mod.RepositoryNotFoundError = RepositoryNotFoundError
    sys.modules["huggingface_hub.utils._errors"] = mod


def load_class_config(config_path: Path | None = None) -> dict[str, Any]:
    path = config_path or (CONFIG_DIR / "th_classes.yaml")
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def model_class_names(config_path: Path | None = None) -> list[str]:
    """All keremberke model class names (indices 0..15 fixed)."""
    cfg = load_class_config(config_path)
    if "model_classes" in cfg:
        return list(cfg["model_classes"])
    return list(cfg["classes"])


def active_class_names(config_path: Path | None = None) -> list[str]:
    """Classes still useful for detection / training (excludes deprecated hero pads)."""
    cfg = load_class_config(config_path)
    if "active_classes" in cfg:
        return list(cfg["active_classes"])
    deprecated = set(deprecated_class_names(config_path))
    return [name for name in model_class_names(config_path) if name not in deprecated]


def deprecated_class_names(config_path: Path | None = None) -> list[str]:
    cfg = load_class_config(config_path)
    return list(cfg.get("deprecated_classes", []))


def deprecated_class_indices(config_path: Path | None = None) -> set[int]:
    model_names = model_class_names(config_path)
    deprecated = set(deprecated_class_names(config_path))
    return {idx for idx, name in enumerate(model_names) if name in deprecated}


def filter_deprecated_yolo_lines(
    lines: list[str],
    *,
    include_deprecated: bool = False,
    config_path: Path | None = None,
) -> tuple[list[str], int]:
    """Drop label lines whose class index is deprecated. Returns (filtered_lines, removed_count)."""
    if include_deprecated:
        return lines, 0
    deprecated = deprecated_class_indices(config_path)
    kept: list[str] = []
    removed = 0
    for line in lines:
        parts = line.strip().split()
        if len(parts) < 5:
            continue
        cls_idx = int(parts[0])
        if cls_idx in deprecated:
            removed += 1
            continue
        kept.append(line)
    return kept, removed


def load_keremberke_yolov5(
    model_id: str = DEFAULT_MODEL_ID,
    *,
    conf: float = 0.25,
    iou: float = 0.45,
    max_det: int = 1000,
):
    """Load keremberke YOLOv5 with PyTorch 2.6+ weights_only workaround."""
    _patch_huggingface_hub_for_yolov5()
    import torch
    import yolov5

    _torch_load = torch.load

    def _load_weights(*args, **kwargs):
        if kwargs.get("weights_only") is None:
            kwargs["weights_only"] = False
        return _torch_load(*args, **kwargs)

    torch.load = _load_weights
    try:
        model = yolov5.load(model_id)
    finally:
        torch.load = _torch_load

    model.conf = conf
    model.iou = iou
    model.max_det = max_det
    return model


def yolov5_predictions_to_yolo_lines(
    predictions,
    class_names: list[str],
    img_width: int,
    img_height: int,
) -> list[str]:
    """Convert YOLOv5 tensor predictions to YOLO normalized label lines."""
    if predictions is None or len(predictions) == 0:
        return []

    lines: list[str] = []
    for row in predictions:
        x1, y1, x2, y2, conf, cls_id = row.tolist()
        cls_idx = int(cls_id)
        if cls_idx < 0 or cls_idx >= len(class_names):
            continue
        cx = ((x1 + x2) / 2) / img_width
        cy = ((y1 + y2) / 2) / img_height
        w = (x2 - x1) / img_width
        h = (y2 - y1) / img_height
        cx = min(max(cx, 0.0), 1.0)
        cy = min(max(cy, 0.0), 1.0)
        w = min(max(w, 0.0), 1.0)
        h = min(max(h, 0.0), 1.0)
        lines.append(f"{cls_idx} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
    return lines
