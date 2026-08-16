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
from gradio.events import SelectData
from PIL import Image, ImageDraw, ImageFont

ML_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ML_ROOT / "src"))

from model_utils import deprecated_class_indices, model_class_names  # noqa: E402

REGRESSION_DIR = ML_ROOT / "tests" / "regression_set"
LABELS_DIR = REGRESSION_DIR / "labels"
CLASSES_PATH = REGRESSION_DIR / "classes.txt"
PORT = 8766
MAX_DISPLAY_WIDTH = 1200

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
Corner = tuple[int, int]
PendingCorner = Corner | None


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


def _load_font() -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 14)
    except OSError:
        return ImageFont.load_default()


def _resize_for_display(img: Image.Image) -> tuple[Image.Image, tuple[int, int]]:
    width, height = img.size
    if width <= MAX_DISPLAY_WIDTH:
        return img.copy(), (width, height)
    scale = MAX_DISPLAY_WIDTH / width
    display = img.resize(
        (MAX_DISPLAY_WIDTH, max(1, round(height * scale))),
        Image.Resampling.LANCZOS,
    )
    return display, display.size


def _box_from_corners(
    corner_a: Corner,
    corner_b: Corner,
    display_size: tuple[int, int],
    class_name: str,
    model_names: list[str],
) -> Box | None:
    display_w, display_h = display_size
    if display_w <= 0 or display_h <= 0:
        return None
    x1, y1 = corner_a
    x2, y2 = corner_b
    xmin, xmax = sorted((x1, x2))
    ymin, ymax = sorted((y1, y2))
    if xmax <= xmin or ymax <= ymin:
        return None
    if class_name not in model_names:
        return None
    cx = ((xmin + xmax) / 2) / display_w
    cy = ((ymin + ymax) / 2) / display_h
    w = (xmax - xmin) / display_w
    h = (ymax - ymin) / display_h
    return model_names.index(class_name), cx, cy, w, h


def _format_box_list(boxes: list[Box], model_names: list[str]) -> str:
    if not boxes:
        return "_Keine Boxen — zweimal auf das Bild klicken (gegenüberliegende Ecken)._"
    lines = []
    for idx, (cls_id, cx, cy, w, h) in enumerate(boxes, start=1):
        name = _class_name(cls_id, model_names)
        lines.append(f"{idx}. **{name}** (id {cls_id}) — cx={cx:.4f}, cy={cy:.4f}, w={w:.4f}, h={h:.4f}")
    return "\n".join(lines)


def _click_hint(pending: PendingCorner) -> str:
    if pending is None:
        return "**Klick 1/2:** Erste Ecke der Box auf dem Bild wählen."
    x, y = pending
    return f"**Klick 2/2:** Zweite Ecke wählen (Ecke 1: {x}, {y}). **Klick zurücksetzen** bricht ab."


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
        self.display_size: tuple[int, int] = (1, 1)
        self._load_boxes_for_current()

    def _current_image(self) -> Path:
        return self.images[self.index]

    def _cache_current(self) -> None:
        self.box_cache[_rel_image_path(self._current_image())] = list(self.boxes)

    def _load_boxes_for_current(self) -> None:
        rel = _rel_image_path(self._current_image())
        if rel in self.box_cache:
            self.boxes = list(self.box_cache[rel])
        else:
            self.boxes = _read_yolo_boxes(_label_path_for(self._current_image()))
        with Image.open(self._current_image()) as img:
            _, self.display_size = _resize_for_display(img.convert("RGB"))

    def progress_text(self) -> str:
        rel = _rel_image_path(self._current_image())
        return f"**Bild {self.index + 1}/{len(self.images)}** — `{rel}` — {len(self.boxes)} Boxen"

    def status_text(self) -> str:
        label_path = _label_path_for(self._current_image())
        if label_path.is_file():
            return f"Label-Datei: `{label_path.relative_to(REGRESSION_DIR)}` (gespeichert)"
        return f"Label-Datei: `{label_path.relative_to(REGRESSION_DIR)}` (noch nicht gespeichert)"

    def render_image(self, pending: PendingCorner = None) -> Image.Image:
        with Image.open(self._current_image()) as source:
            display, self.display_size = _resize_for_display(source.convert("RGB"))
        draw = ImageDraw.Draw(display)
        font = _load_font()
        display_w, display_h = self.display_size

        for cls_id, cx, cy, w, h in self.boxes:
            x1 = (cx - w / 2) * display_w
            y1 = (cy - h / 2) * display_h
            x2 = (cx + w / 2) * display_w
            y2 = (cy + h / 2) * display_h
            color = BOX_COLORS[cls_id % len(BOX_COLORS)]
            draw.rectangle([x1, y1, x2, y2], outline=color, width=2)
            name = _class_name(cls_id, self.model_names)
            draw.text((x1 + 2, max(y1 - 16, 0)), name, fill=color, font=font)

        if pending is not None:
            px, py = pending
            draw.ellipse([px - 5, py - 5, px + 5, py + 5], outline="#00ff00", width=2)
            draw.line([px - 8, py, px + 8, py], fill="#00ff00", width=1)
            draw.line([px, py - 8, px, py + 8], fill="#00ff00", width=1)

        return display

    def render(self, pending: PendingCorner = None) -> tuple[Image.Image, str, str, str, str]:
        return (
            self.render_image(pending),
            self.progress_text(),
            _format_box_list(self.boxes, self.model_names),
            self.status_text(),
            _click_hint(pending),
        )

    def on_image_click(self, evt: SelectData, class_name: str, pending: PendingCorner) -> tuple:
        index = evt.index
        if not index or index[0] is None or index[1] is None:
            return self.render(pending) + (pending,)

        corner = (int(index[0]), int(index[1]))
        if pending is None:
            return self.render(corner) + (corner,)

        box = _box_from_corners(pending, corner, self.display_size, class_name, self.model_names)
        if box is not None:
            self.boxes.append(box)
            self._cache_current()
        return self.render(None) + (None,)

    def reset_clicks(self) -> tuple:
        return self.render(None) + (None,)

    def remove_last(self) -> tuple:
        if self.boxes:
            self.boxes.pop()
            self._cache_current()
        return self.render(None) + (None,)

    def save_current(self) -> tuple:
        _write_yolo_boxes(_label_path_for(self._current_image()), self.boxes)
        self._cache_current()
        return self.render(None) + (None,)

    def save_and_next(self) -> tuple:
        _write_yolo_boxes(_label_path_for(self._current_image()), self.boxes)
        self._cache_current()
        if self.index < len(self.images) - 1:
            self.index += 1
            self._load_boxes_for_current()
        return self.render(None) + (None,)

    def prev_image(self) -> tuple:
        if self.index > 0:
            self._cache_current()
            self.index -= 1
            self._load_boxes_for_current()
        return self.render(None) + (None,)

    def next_image(self) -> tuple:
        if self.index < len(self.images) - 1:
            self._cache_current()
            self.index += 1
            self._load_boxes_for_current()
        return self.render(None) + (None,)


def create_app() -> gr.Blocks:
    session = LabelSession()
    img0, prog0, boxes0, status0, hint0 = session.render()
    class_choices = session.class_names
    legend = " · ".join(f"{session.model_names.index(n)}:{n}" for n in session.class_names)

    with gr.Blocks(title="CoC Manuelles Labeling") as app:
        gr.Markdown("# Manuelles Labeling — Regression-Set")
        gr.Markdown(
            "YOLO-Boxen per **Zwei-Klick-Modus** setzen: Klasse wählen, **erste Ecke** klicken, "
            "**zweite Ecke** klicken — die Box wird sofort übernommen. "
            "Speichern schreibt `.txt` nach `labels/th15/` bzw. `labels/th16/`.\n\n"
            f"**Aktive Klassen:** {legend}"
        )

        pending_state = gr.State(None)

        with gr.Row():
            image = gr.Image(
                value=img0,
                label="Box zeichnen (zwei Klicks: Ecke 1, Ecke 2)",
                type="pil",
                format="png",
                interactive=True,
                sources=[],
                buttons=[],
                height=720,
            )

        click_hint = gr.Markdown(hint0)
        progress = gr.Markdown(prog0)
        box_list = gr.Markdown(boxes0)
        status = gr.Markdown(status0)

        with gr.Row():
            class_in = gr.Dropdown(choices=class_choices, value=class_choices[0], label="Klasse")

        with gr.Row():
            btn_reset = gr.Button("Klick zurücksetzen", variant="secondary")
            btn_remove = gr.Button("Letzte löschen")

        with gr.Row():
            btn_prev = gr.Button("Zurück")
            btn_next = gr.Button("Weiter")
            btn_save = gr.Button("Speichern", variant="secondary")
            btn_save_next = gr.Button("Speichern & Weiter", variant="primary")

        outputs = [image, progress, box_list, status, click_hint]
        outputs_with_pending = outputs + [pending_state]
        event_kwargs = {"show_progress": "hidden"}

        image.select(
            session.on_image_click,
            inputs=[class_in, pending_state],
            outputs=outputs_with_pending,
            **event_kwargs,
        )
        btn_reset.click(session.reset_clicks, outputs=outputs_with_pending, **event_kwargs)
        btn_remove.click(session.remove_last, outputs=outputs_with_pending, **event_kwargs)
        btn_prev.click(session.prev_image, outputs=outputs_with_pending, **event_kwargs)
        btn_next.click(session.next_image, outputs=outputs_with_pending, **event_kwargs)
        btn_save.click(session.save_current, outputs=outputs_with_pending, **event_kwargs)
        btn_save_next.click(session.save_and_next, outputs=outputs_with_pending, **event_kwargs)

    return app


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print(f"\nÖffne http://127.0.0.1:{PORT}\n")
    create_app().launch(server_name="127.0.0.1", server_port=PORT, share=False, show_error=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
