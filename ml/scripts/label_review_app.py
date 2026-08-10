#!/usr/bin/env python3
"""One-click pseudo-label review UI for regression screenshots.

Run:
    cd ml && python scripts/label_review_app.py
    Open http://localhost:8765
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import gradio as gr
from PIL import Image, ImageDraw, ImageFont

# Allow imports from ml/src
ML_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ML_ROOT.parent
sys.path.insert(0, str(ML_ROOT / "src"))

from model_utils import (  # noqa: E402
    active_class_names,
    load_keremberke_yolov5,
)
from pseudo_label import load_train_config, pseudo_label_image  # noqa: E402

REGRESSION_DIR = ML_ROOT / "tests" / "regression_set"
LABELS_DIR = REGRESSION_DIR / "labels"
REVIEWS_PATH = REGRESSION_DIR / "_label_reviews.json"
REJECTED_DIR = REGRESSION_DIR / "_rejected"
CONFIG_PATH = ML_ROOT / "configs" / "train_config.yaml"
TH_LEVELS = {"th13", "th15", "th16"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
PORT = 8765

_model = None
_model_conf: float | None = None

BOX_COLORS = [
    "#e6194b", "#3cb44b", "#ffe119", "#4363d8",
    "#f58231", "#911eb4", "#46f0f0", "#f032e6",
    "#bcf60c", "#fabebe", "#008080", "#e6beff",
    "#9a6324", "#fffac8", "#800000", "#aaffc3",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_reviews() -> dict:
    if REVIEWS_PATH.is_file():
        return json.loads(REVIEWS_PATH.read_text(encoding="utf-8"))
    return {"reviews": [], "rejection_counts": {}}


def _save_reviews(data: dict) -> None:
    REVIEWS_PATH.parent.mkdir(parents=True, exist_ok=True)
    REVIEWS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _rel_image_path(image_path: Path) -> str:
    return str(image_path.relative_to(REGRESSION_DIR))


def find_review_images(*, include_extras: bool = False) -> list[Path]:
    images: list[Path] = []
    for path in sorted(REGRESSION_DIR.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        parts = {p.lower() for p in path.parts}
        if "_rejected" in parts or path.name.startswith("."):
            continue
        if not include_extras and "_extras" in parts:
            continue
        if "labels" in parts:
            continue
        if path.parent.name.lower() not in TH_LEVELS:
            continue
        images.append(path)
    return images


def _approved_paths(reviews_data: dict) -> set[str]:
    return {r["path"] for r in reviews_data.get("reviews", []) if r.get("status") == "approved"}


def _pending_images(reviews_data: dict) -> list[Path]:
    approved = _approved_paths(reviews_data)
    rejected_final = {
        r["path"]
        for r in reviews_data.get("reviews", [])
        if r.get("status") == "rejected" and r.get("action_taken") == "excluded_to_rejected"
    }
    return [
        img
        for img in find_review_images()
        if _rel_image_path(img) not in approved and _rel_image_path(img) not in rejected_final
    ]


def _label_path_for(image_path: Path) -> Path:
    rel = image_path.relative_to(REGRESSION_DIR)
    return LABELS_DIR / rel.with_suffix(".txt")


def _read_yolo_boxes(label_path: Path) -> list[tuple[int, float, float, float, float]]:
    if not label_path.is_file():
        return []
    boxes: list[tuple[int, float, float, float, float]] = []
    for line in label_path.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split()
        if len(parts) < 5:
            continue
        cls_id = int(parts[0])
        cx, cy, w, h = map(float, parts[1:5])
        boxes.append((cls_id, cx, cy, w, h))
    return boxes


def _get_model(conf: float):
    global _model, _model_conf
    if _model is None or _model_conf != conf:
        cfg = load_train_config(CONFIG_PATH)
        pl_cfg = cfg.get("pseudo_label", {})
        _model = load_keremberke_yolov5(conf=conf, iou=pl_cfg.get("iou", 0.45))
        _model_conf = conf
    else:
        _model.conf = conf
    return _model


def regenerate_labels(image_path: Path, *, conf: float) -> int:
    cfg = load_train_config(CONFIG_PATH)
    pl_cfg = cfg.get("pseudo_label", {})
    imgsz = pl_cfg.get("imgsz", 640)
    class_names = active_class_names()
    model = _get_model(conf)
    lines, count = pseudo_label_image(model, image_path, class_names, imgsz)
    label_path = _label_path_for(image_path)
    label_path.parent.mkdir(parents=True, exist_ok=True)
    label_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return count


def _move_to_rejected(image_path: Path) -> None:
    rel = image_path.relative_to(REGRESSION_DIR)
    dest_image = REJECTED_DIR / rel
    dest_image.parent.mkdir(parents=True, exist_ok=True)
    if image_path.exists():
        shutil.move(str(image_path), str(dest_image))

    label_path = _label_path_for(image_path)
    if label_path.is_file():
        dest_label = REJECTED_DIR / "labels" / rel.with_suffix(".txt")
        dest_label.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(label_path), str(dest_label))


def render_annotated_image(image_path: Path, class_names: list[str]) -> Image.Image:
    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    width, height = img.size
    boxes = _read_yolo_boxes(_label_path_for(image_path))

    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 14)
    except OSError:
        font = ImageFont.load_default()

    for cls_id, cx, cy, w, h in boxes:
        x1 = (cx - w / 2) * width
        y1 = (cy - h / 2) * height
        x2 = (cx + w / 2) * width
        y2 = (cy + h / 2) * height
        color = BOX_COLORS[cls_id % len(BOX_COLORS)]
        draw.rectangle([x1, y1, x2, y2], outline=color, width=2)
        name = class_names[cls_id] if 0 <= cls_id < len(class_names) else str(cls_id)
        draw.text((x1 + 2, max(y1 - 16, 0)), name, fill=color, font=font)

    return img


def _class_legend(class_names: list[str]) -> str:
    return " · ".join(f"{i}:{n}" for i, n in enumerate(class_names))


def _append_review(reviews_data: dict, *, path: str, status: str, action_taken: str) -> None:
    reviews_data.setdefault("reviews", []).append(
        {"path": path, "status": status, "timestamp": _utc_now(), "action_taken": action_taken}
    )


class ReviewSession:
    def __init__(self) -> None:
        self.class_names = active_class_names()
        self.reviews_data = _load_reviews()
        self.queue = _pending_images(self.reviews_data)
        self.index = 0

    def refresh_queue(self) -> None:
        self.queue = _pending_images(self.reviews_data)
        if self.index >= len(self.queue):
            self.index = max(0, len(self.queue) - 1)

    def progress_text(self) -> str:
        total = len(find_review_images())
        approved = len(_approved_paths(self.reviews_data))
        rejected = sum(
            1
            for r in self.reviews_data.get("reviews", [])
            if r.get("status") == "rejected" and r.get("action_taken") == "excluded_to_rejected"
        )
        pending = len(self.queue)
        if self.queue:
            current = min(self.index + 1, len(self.queue))
            return f"Bild {current} von {pending} ausstehend ({approved} richtig, {rejected} ausgeschlossen, {total} gesamt)"
        return f"Fertig — {approved} richtig, {rejected} ausgeschlossen von {total} Bildern"

    def current_image(self) -> tuple[Image.Image | None, str, str]:
        if not self.queue:
            return None, self.progress_text(), self.summary_text()

        image_path = self.queue[self.index]
        rel = _rel_image_path(image_path)
        box_count = len(_read_yolo_boxes(_label_path_for(image_path)))
        info = f"**{rel}** — {box_count} Boxen"
        rejections = self.reviews_data.get("rejection_counts", {}).get(rel, 0)
        if rejections:
            info += f" (Falsch-Klicks: {rejections})"
        return render_annotated_image(image_path, self.class_names), self.progress_text(), info

    def summary_text(self) -> str:
        approved = [r for r in self.reviews_data.get("reviews", []) if r.get("status") == "approved"]
        rejected = [
            r for r in self.reviews_data.get("reviews", [])
            if r.get("status") == "rejected" and r.get("action_taken") == "excluded_to_rejected"
        ]
        regen = [r for r in self.reviews_data.get("reviews", []) if r.get("action_taken") == "regenerated_conf_0.15"]
        lines = [
            f"✅ {len(approved)} für Training freigegeben",
            f"❌ {len(rejected)} nach _rejected/ verschoben",
            f"🔄 {len(regen)} neu pseudo-gelabelt (conf=0.15)",
        ]
        if not self.queue:
            lines.append("\nAlle Bilder bearbeitet. Klicke **Dataset neu bauen**.")
        return "\n".join(lines)

    def approve(self) -> tuple:
        if not self.queue:
            img, prog, info = self.current_image()
            return img, prog, info, self.summary_text()

        rel = _rel_image_path(self.queue[self.index])
        _append_review(self.reviews_data, path=rel, status="approved", action_taken="approved_for_training")
        _save_reviews(self.reviews_data)
        self.refresh_queue()
        img, prog, info = self.current_image()
        return img, prog, info, self.summary_text()

    def reject(self) -> tuple:
        if not self.queue:
            img, prog, info = self.current_image()
            return img, prog, info, self.summary_text()

        image_path = self.queue[self.index]
        rel = _rel_image_path(image_path)
        counts = self.reviews_data.setdefault("rejection_counts", {})
        counts[rel] = counts.get(rel, 0) + 1

        if counts[rel] == 1:
            box_count = regenerate_labels(image_path, conf=0.15)
            _append_review(self.reviews_data, path=rel, status="rejected", action_taken="regenerated_conf_0.15")
            _save_reviews(self.reviews_data)
            msg = f"Neu gelabelt mit conf=0.15 ({box_count} Boxen). Bitte erneut prüfen."
        else:
            _move_to_rejected(image_path)
            _append_review(self.reviews_data, path=rel, status="rejected", action_taken="excluded_to_rejected")
            _save_reviews(self.reviews_data)
            self.refresh_queue()
            msg = f"{rel} nach _rejected/ verschoben und ausgeschlossen."

        img, prog, info = self.current_image()
        return img, prog, f"{info}\n\n{msg}", self.summary_text()

    def skip(self) -> tuple:
        if not self.queue:
            img, prog, info = self.current_image()
            return img, prog, info, self.summary_text()

        self.index = (self.index + 1) % len(self.queue)
        img, prog, info = self.current_image()
        return img, prog, info, self.summary_text()

    def rebuild_dataset(self) -> str:
        approved = _approved_paths(self.reviews_data)
        if not approved:
            return "Keine freigegebenen Labels — zuerst **Richtig** klicken."

        cmd = [
            sys.executable, "-m", "dataset.build_dataset",
            "--include-demo", "--include-regression", "--include-pseudo-labels",
            "--approved-reviews", str(REVIEWS_PATH),
        ]
        env = {**dict(subprocess.os.environ), "PYTHONPATH": str(REPO_ROOT / "data-pipeline" / "src")}
        try:
            result = subprocess.run(
                cmd, cwd=str(REPO_ROOT / "data-pipeline"),
                capture_output=True, text=True, check=True, env=env,
            )
        except subprocess.CalledProcessError as exc:
            return f"Fehler beim Dataset-Bau:\n{exc.stderr or exc.stdout}"

        return f"{self.summary_text()}\n\nDataset neu gebaut ({len(approved)} freigegebene Regression-Bilder).\n\n{result.stdout[-800:]}"


def create_app() -> gr.Blocks:
    session = ReviewSession()
    img0, prog0, info0 = session.current_image()

    with gr.Blocks(title="CoC Label Review") as app:
        gr.Markdown("# Pseudo-Label Review")
        gr.Markdown("Nur **Richtig** oder **Falsch** klicken — der Rest passiert automatisch.")

        with gr.Row():
            image_out = gr.Image(value=img0, label="Screenshot mit Pseudo-Labels", type="pil")
        progress_out = gr.Markdown(prog0)
        info_out = gr.Markdown(info0)
        summary_out = gr.Markdown(session.summary_text())

        with gr.Row():
            btn_right = gr.Button("Richtig", variant="primary", scale=2)
            btn_wrong = gr.Button("Falsch", variant="stop", scale=2)
            btn_skip = gr.Button("Weiter", scale=1)

        btn_rebuild = gr.Button("Dataset neu bauen")
        rebuild_out = gr.Markdown("")
        gr.Markdown(f"**Klassen:** {_class_legend(session.class_names)}")

        btn_right.click(session.approve, outputs=[image_out, progress_out, info_out, summary_out])
        btn_wrong.click(session.reject, outputs=[image_out, progress_out, info_out, summary_out])
        btn_skip.click(session.skip, outputs=[image_out, progress_out, info_out, summary_out])
        btn_rebuild.click(session.rebuild_dataset, outputs=[rebuild_out])

    return app


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print(f"\nÖffne http://localhost:{PORT}\n")
    create_app().launch(server_name="127.0.0.1", server_port=PORT, share=False, show_error=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
