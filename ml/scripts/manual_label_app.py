#!/usr/bin/env python3
"""Browser-based manual YOLO labeling for regression war bases.

Run:
    cd ml && ./scripts/run_manual_label.sh
    Open http://127.0.0.1:8766
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import gradio as gr
from gradio_image_annotation import image_annotator
from PIL import Image, ImageDraw, ImageFont

ML_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ML_ROOT / "src"))

from model_utils import deprecated_class_indices, model_class_names  # noqa: E402

REGRESSION_DIR = ML_ROOT / "tests" / "regression_set"
LABELS_DIR = REGRESSION_DIR / "labels"
CLASSES_PATH = REGRESSION_DIR / "classes.txt"
PORT = 8766

CORE_IMAGES = [
    REGRESSION_DIR / "th15" / "war_base_illyrian_god.png",
    REGRESSION_DIR / "th15" / "war_base_cocbase_wizztower_ring.png",
    REGRESSION_DIR / "th16" / "war_base_cocbase_volcanic_warmap.png",
    REGRESSION_DIR / "th16" / "war_base_cocbase_sakura_scenery.png",
]

BOX_COLORS = [
    "#e6194b", "#3cb44b", "#ffe119", "#4363d8",
    "#f58231", "#911eb4", "#46f0f0", "#f032e6",
    "#bcf60c", "#fabebe", "#008080", "#e6beff",
    "#9a6324", "#fffac8", "#800000", "#aaffc3",
]

Box = tuple[int, float, float, float, float]
AnnotatorValue = dict


def _load_class_names() -> list[str]:
    if not CLASSES_PATH.is_file():
        raise FileNotFoundError(f"classes.txt fehlt: {CLASSES_PATH}")
    names = [line.strip() for line in CLASSES_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not names:
        raise ValueError("classes.txt ist leer")
    return names


def _rel_image_path(image_path: Path) -> str:
    return str(image_path.relative_to(REGRESSION_DIR))


def _label_path_for(image_path: Path) -> Path:
    rel = image_path.relative_to(REGRESSION_DIR)
    return LABELS_DIR / rel.with_suffix(".txt")


def _read_yolo_boxes(label_path: Path) -> list[Box]:
    if not label_path.is_file():
        return []
    deprecated = deprecated_class_indices()
    boxes: list[Box] = []
    for line in label_path.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split()
        if len(parts) < 5:
            continue
        cls_id = int(parts[0])
        if cls_id in deprecated:
            continue
        cx, cy, w, h = map(float, parts[1:5])
        boxes.append((cls_id, cx, cy, w, h))
    return boxes


def _write_yolo_boxes(label_path: Path, boxes: list[Box]) -> None:
    label_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{cls_id} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}" for cls_id, cx, cy, w, h in boxes]
    label_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _class_name(cls_id: int, model_names: list[str]) -> str:
    if 0 <= cls_id < len(model_names):
        return model_names[cls_id]
    return str(cls_id)


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    value = hex_color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _label_colors_for(class_names: list[str], model_names: list[str]) -> list[str]:
    colors: list[str] = []
    for name in class_names:
        cls_id = model_names.index(name) if name in model_names else 0
        colors.append(BOX_COLORS[cls_id % len(BOX_COLORS)])
    return colors


def _image_size(value: AnnotatorValue | None) -> tuple[int, int]:
    if not value or value.get("image") is None:
        return 1, 1
    image = value["image"]
    if isinstance(image, Image.Image):
        return image.size
    if isinstance(image, str):
        with Image.open(image) as img:
            return img.size
    if hasattr(image, "shape"):
        height, width = image.shape[:2]
        return width, height
    return 1, 1


def boxes_to_annotator_value(image_path: Path, boxes: list[Box], model_names: list[str]) -> AnnotatorValue:
    img = Image.open(image_path).convert("RGB")
    width, height = img.size
    ann_boxes = []
    for cls_id, cx, cy, w, h in boxes:
        x1 = (cx - w / 2) * width
        y1 = (cy - h / 2) * height
        x2 = (cx + w / 2) * width
        y2 = (cy + h / 2) * height
        name = _class_name(cls_id, model_names)
        ann_boxes.append(
            {
                "xmin": round(x1),
                "ymin": round(y1),
                "xmax": round(x2),
                "ymax": round(y2),
                "label": name,
                "color": _hex_to_rgb(BOX_COLORS[cls_id % len(BOX_COLORS)]),
            }
        )
    return {"image": img, "boxes": ann_boxes}


def annotator_value_to_boxes(value: AnnotatorValue | None, model_names: list[str]) -> list[Box]:
    if not value:
        return []
    width, height = _image_size(value)
    boxes: list[Box] = []
    for box in value.get("boxes") or []:
        xmin, ymin = float(box["xmin"]), float(box["ymin"])
        xmax, ymax = float(box["xmax"]), float(box["ymax"])
        if xmax <= xmin or ymax <= ymin:
            continue
        cx = ((xmin + xmax) / 2) / width
        cy = ((ymin + ymax) / 2) / height
        w = (xmax - xmin) / width
        h = (ymax - ymin) / height
        label = (box.get("label") or "").strip()
        if label not in model_names:
            continue
        cls_id = model_names.index(label)
        boxes.append((cls_id, cx, cy, w, h))
    return boxes


def render_annotated_image(image_path: Path, boxes: list[Box], model_names: list[str]) -> Image.Image:
    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    width, height = img.size

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
        name = _class_name(cls_id, model_names)
        draw.text((x1 + 2, max(y1 - 16, 0)), name, fill=color, font=font)

    return img


def _format_box_list(boxes: list[Box], model_names: list[str]) -> str:
    if not boxes:
        return "_Keine Boxen — Rechteck auf dem Bild zeichnen und „Box übernehmen“ klicken._"
    lines = []
    for idx, (cls_id, cx, cy, w, h) in enumerate(boxes, start=1):
        name = _class_name(cls_id, model_names)
        lines.append(f"{idx}. **{name}** (id {cls_id}) — cx={cx:.4f}, cy={cy:.4f}, w={w:.4f}, h={h:.4f}")
    return "\n".join(lines)


class LabelSession:
    def __init__(self) -> None:
        self.model_names = model_class_names()
        self.class_names = _load_class_names()
        self.images = [p for p in CORE_IMAGES if p.is_file()]
        if not self.images:
            raise FileNotFoundError("Keine Regression-Bilder in th15/ oder th16/ gefunden")
        self.index = 0
        self.box_cache: dict[str, list[Box]] = {}
        self.boxes: list[Box] = []
        self._load_boxes_for_current()

    def _current_image(self) -> Path:
        return self.images[self.index]

    def _cache_current(self) -> None:
        self.box_cache[_rel_image_path(self._current_image())] = list(self.boxes)

    def _load_boxes_for_current(self) -> None:
        rel = _rel_image_path(self._current_image())
        if rel in self.box_cache:
            self.boxes = list(self.box_cache[rel])
            return
        self.boxes = _read_yolo_boxes(_label_path_for(self._current_image()))

    def progress_text(self) -> str:
        rel = _rel_image_path(self._current_image())
        return f"**Bild {self.index + 1}/{len(self.images)}** — `{rel}` — {len(self.boxes)} Boxen"

    def status_text(self) -> str:
        label_path = _label_path_for(self._current_image())
        if label_path.is_file():
            return f"Label-Datei: `{label_path.relative_to(REGRESSION_DIR)}` (gespeichert)"
        return f"Label-Datei: `{label_path.relative_to(REGRESSION_DIR)}` (noch nicht gespeichert)"

    def annotator_value(self) -> AnnotatorValue:
        return boxes_to_annotator_value(self._current_image(), self.boxes, self.model_names)

    def render(self) -> tuple[AnnotatorValue, Image.Image, str, str, str]:
        return (
            self.annotator_value(),
            render_annotated_image(self._current_image(), self.boxes, self.model_names),
            self.progress_text(),
            _format_box_list(self.boxes, self.model_names),
            self.status_text(),
        )

    def _apply_annotator(self, value: AnnotatorValue | None, class_name: str) -> None:
        if not value:
            return
        boxes = value.get("boxes") or []
        if boxes:
            last = boxes[-1]
            last["label"] = class_name
            cls_id = self.model_names.index(class_name)
            last["color"] = _hex_to_rgb(BOX_COLORS[cls_id % len(BOX_COLORS)])
        self.boxes = annotator_value_to_boxes(value, self.model_names)
        self._cache_current()

    def accept_box(self, value: AnnotatorValue | None, class_name: str) -> tuple:
        self._apply_annotator(value, class_name)
        return self.render()

    def sync_annotator(self, value: AnnotatorValue | None) -> tuple:
        if value:
            self.boxes = annotator_value_to_boxes(value, self.model_names)
            self._cache_current()
        return self.render()

    def remove_last(self) -> tuple:
        if self.boxes:
            self.boxes.pop()
            self._cache_current()
        return self.render()

    def save_current(self, value: AnnotatorValue | None) -> tuple:
        if value:
            self.boxes = annotator_value_to_boxes(value, self.model_names)
        _write_yolo_boxes(_label_path_for(self._current_image()), self.boxes)
        self._cache_current()
        return self.render()

    def save_and_next(self, value: AnnotatorValue | None) -> tuple:
        if value:
            self.boxes = annotator_value_to_boxes(value, self.model_names)
        _write_yolo_boxes(_label_path_for(self._current_image()), self.boxes)
        self._cache_current()
        if self.index < len(self.images) - 1:
            self.index += 1
            self._load_boxes_for_current()
        return self.render()

    def prev_image(self, value: AnnotatorValue | None) -> tuple:
        if value:
            self.boxes = annotator_value_to_boxes(value, self.model_names)
        if self.index > 0:
            self._cache_current()
            self.index -= 1
            self._load_boxes_for_current()
        return self.render()

    def next_image(self, value: AnnotatorValue | None) -> tuple:
        if value:
            self.boxes = annotator_value_to_boxes(value, self.model_names)
        if self.index < len(self.images) - 1:
            self._cache_current()
            self.index += 1
            self._load_boxes_for_current()
        return self.render()


def create_app() -> gr.Blocks:
    session = LabelSession()
    ann0, preview0, prog0, boxes0, status0 = session.render()
    class_choices = session.class_names
    label_colors = _label_colors_for(class_choices, session.model_names)
    legend = " · ".join(f"{session.model_names.index(n)}:{n}" for n in session.class_names)

    with gr.Blocks(title="CoC Manuelles Labeling") as app:
        gr.Markdown("# Manuelles Labeling — Regression-Set")
        gr.Markdown(
            "Zeichne YOLO-Boxen **direkt auf dem Bild** (Maus ziehen wie in labelImg). "
            "Klasse wählen, Rechteck aufziehen, dann **Box übernehmen**. "
            "Speichern schreibt `.txt` nach `labels/th15/` bzw. `labels/th16/`.\n\n"
            f"**Aktive Klassen:** {legend}"
        )

        with gr.Row():
            annotator = image_annotator(
                value=ann0,
                label="Box zeichnen (ziehen oder zwei Klicks)",
                label_list=class_choices,
                label_colors=label_colors,
                use_default_label=True,
                image_type="pil",
                sources=[],
                show_clear_button=False,
                show_download_button=False,
                height=720,
                interactive=True,
            )

        with gr.Row():
            preview = gr.Image(value=preview0, label="Vorschau mit allen Boxen", type="pil", interactive=False)

        progress = gr.Markdown(prog0)
        box_list = gr.Markdown(boxes0)
        status = gr.Markdown(status0)

        with gr.Row():
            class_in = gr.Dropdown(choices=class_choices, value=class_choices[0], label="Klasse")

        with gr.Row():
            btn_accept = gr.Button("Box übernehmen", variant="secondary")
            btn_remove = gr.Button("Letzte löschen")

        with gr.Row():
            btn_prev = gr.Button("Zurück")
            btn_next = gr.Button("Weiter")
            btn_save = gr.Button("Speichern", variant="secondary")
            btn_save_next = gr.Button("Speichern & Weiter", variant="primary")

        outputs = [annotator, preview, progress, box_list, status]

        btn_accept.click(session.accept_box, inputs=[annotator, class_in], outputs=outputs)
        btn_remove.click(session.remove_last, outputs=outputs)
        btn_prev.click(session.prev_image, inputs=[annotator], outputs=outputs)
        btn_next.click(session.next_image, inputs=[annotator], outputs=outputs)
        btn_save.click(session.save_current, inputs=[annotator], outputs=outputs)
        btn_save_next.click(session.save_and_next, inputs=[annotator], outputs=outputs)
        annotator.change(session.sync_annotator, inputs=[annotator], outputs=outputs)

    return app


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print(f"\nÖffne http://127.0.0.1:{PORT}\n")
    create_app().launch(server_name="127.0.0.1", server_port=PORT, share=False, show_error=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
