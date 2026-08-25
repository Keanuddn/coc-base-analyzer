#!/usr/bin/env python3
"""Browser-based manual YOLO labeling — FastAPI + canvas (no Gradio).

Run:
    cd ml && ./scripts/run_manual_label.sh
    Open http://127.0.0.1:8766
"""

from __future__ import annotations

import argparse
import io
import logging
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from PIL import Image
from pydantic import BaseModel, Field

ML_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ML_ROOT / "src"))

from model_utils import (  # noqa: E402
    active_class_names,
    deprecated_class_indices,
    load_keremberke_yolov5,
    model_class_names,
)

REGRESSION_DIR = ML_ROOT / "tests" / "regression_set"
LABELS_DIR = REGRESSION_DIR / "labels"
CLASSES_PATH = REGRESSION_DIR / "classes.txt"
PORT = 8766
MAX_DISPLAY_WIDTH = 1200
PROPOSAL_CONF = 0.25
PROPOSAL_COLOR = "#ff8800"
V6_WEIGHTS = ML_ROOT / "runs" / "coc_yolo_v6" / "weights" / "best.pt"
V5_WEIGHTS = ML_ROOT / "runs" / "coc_yolo_v5" / "weights" / "best.pt"
V6_LAST = ML_ROOT / "runs" / "coc_yolo_v6" / "weights" / "last.pt"

CORE_IMAGES = [
    REGRESSION_DIR / "th15" / "war_base_illyrian_god.png",
    REGRESSION_DIR / "th15" / "war_base_cocbase_wizztower_ring.png",
    REGRESSION_DIR / "th16" / "war_base_cocbase_volcanic_warmap.png",
    REGRESSION_DIR / "th16" / "war_base_cocbase_sakura_scenery.png",
]

# Five new unlabeled screenshots — do not mix with the already-labeled war bases.
UNLABELED_QUEUE = [
    REGRESSION_DIR / "th18" / "th18_vinsmoke_sanji.png",
    REGRESSION_DIR / "th18" / "th18_lukas.png",
    REGRESSION_DIR / "th18" / "th18_aggressor.png",
    REGRESSION_DIR / "th17" / "th17_img_7307.png",
    REGRESSION_DIR / "th17" / "th17_img_7306.png",
]

BOX_COLORS = [
    "#e6194b", "#3cb44b", "#ffe119", "#4363d8",
    "#f58231", "#911eb4", "#46f0f0", "#f032e6",
    "#bcf60c", "#fabebe", "#008080", "#e6beff",
    "#9a6324", "#fffac8", "#800000", "#aaffc3",
]

Box = tuple[int, float, float, float, float]


def _load_class_names() -> list[str]:
    """Dropdown: yaml active_classes (v5/v6 27+ plus TH14–18). classes.txt is the fallback."""
    try:
        names = active_class_names()
        if names:
            return names
    except Exception as exc:  # noqa: BLE001
        logging.warning("th_classes.yaml active_classes unavailable (%s); falling back to classes.txt", exc)
    if not CLASSES_PATH.is_file():
        raise FileNotFoundError(f"classes.txt fehlt: {CLASSES_PATH}")
    names = [line.strip() for line in CLASSES_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not names:
        raise ValueError("classes.txt ist leer")
    return names


def _v6_train_in_flight(max_age_s: float = 180.0) -> bool:
    """True if coc_yolo_v6 last.pt was rewritten recently (train still running)."""
    if not V6_LAST.is_file():
        return False
    return (time.time() - V6_LAST.stat().st_mtime) < max_age_s


def proposal_weights_path() -> Path | None:
    """Prefer v6 when idle; otherwise v5 so we do not fight an in-flight train."""
    if V6_WEIGHTS.is_file() and not _v6_train_in_flight():
        return V6_WEIGHTS
    if V5_WEIGHTS.is_file():
        return V5_WEIGHTS
    if V6_WEIGHTS.is_file():
        return V6_WEIGHTS
    return None


def _rel_image_path(image_path: Path) -> str:
    return str(image_path.relative_to(REGRESSION_DIR))


def _label_path_for(image_path: Path) -> Path:
    rel = image_path.relative_to(REGRESSION_DIR)
    return LABELS_DIR / rel.with_suffix(".txt")


def yolo_lines_to_boxes(lines: list[str]) -> list[Box]:
    """Parse YOLO label lines and drop deprecated hero-pad classes."""
    deprecated = deprecated_class_indices()
    boxes: list[Box] = []
    for line in lines:
        parts = line.strip().split()
        if len(parts) < 5:
            continue
        cls_id = int(parts[0])
        if cls_id in deprecated:
            continue
        cx, cy, w, h = map(float, parts[1:5])
        boxes.append((cls_id, cx, cy, w, h))
    return boxes


def filter_proposal_boxes(boxes: list[Box]) -> list[Box]:
    deprecated = deprecated_class_indices()
    return [box for box in boxes if box[0] not in deprecated]


def _read_yolo_boxes(label_path: Path) -> list[Box]:
    if not label_path.is_file():
        return []
    return yolo_lines_to_boxes(label_path.read_text(encoding="utf-8").splitlines())


def _write_yolo_boxes(label_path: Path, boxes: list[Box]) -> None:
    label_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{cls_id} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}" for cls_id, cx, cy, w, h in boxes]
    label_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _class_name(cls_id: int, model_names: list[str]) -> str:
    if 0 <= cls_id < len(model_names):
        return model_names[cls_id]
    return str(cls_id)

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


def _box_from_display_rect(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    display_size: tuple[int, int],
    class_name: str,
    model_names: list[str],
) -> Box | None:
    display_w, display_h = display_size
    if display_w <= 0 or display_h <= 0:
        return None
    xmin, xmax = sorted((x1, x2))
    ymin, ymax = sorted((y1, y2))
    if xmax - xmin < 2 or ymax - ymin < 2:
        return None
    if class_name not in model_names:
        return None
    cx = ((xmin + xmax) / 2) / display_w
    cy = ((ymin + ymax) / 2) / display_h
    w = (xmax - xmin) / display_w
    h = (ymax - ymin) / display_h
    return model_names.index(class_name), cx, cy, w, h


_proposal_model = None
_proposal_model_error: str | None = None
_proposal_backend: str | None = None


def get_proposal_model():
    """Load fine-tuned Ultralytics weights on CPU; keremberke is the fallback."""
    global _proposal_model, _proposal_model_error, _proposal_backend
    if _proposal_model is not None:
        return _proposal_model
    if _proposal_model_error is not None:
        raise RuntimeError(_proposal_model_error)
    weights = proposal_weights_path()
    try:
        if weights is not None:
            from ultralytics import YOLO

            _proposal_model = YOLO(str(weights))
            _proposal_backend = f"ultralytics:{weights}"
            logging.info("proposal model %s (CPU, conf=%.2f)", weights, PROPOSAL_CONF)
            return _proposal_model
        _proposal_model = load_keremberke_yolov5(conf=PROPOSAL_CONF, iou=0.45)
        _proposal_backend = "keremberke"
        logging.info("proposal model keremberke (conf=%.2f)", PROPOSAL_CONF)
        return _proposal_model
    except Exception as exc:  # noqa: BLE001 — surface load failures in the UI
        _proposal_model_error = str(exc)
        raise RuntimeError(_proposal_model_error) from exc


def ultralytics_boxes(model, image_path: Path, conf: float) -> list[Box]:
    results = model.predict(
        source=str(image_path),
        conf=conf,
        iou=0.45,
        device="cpu",
        verbose=False,
    )
    lines: list[str] = []
    for result in results:
        boxes = result.boxes
        if boxes is None:
            continue
        for box in boxes:
            cls_id = int(box.cls.item())
            cx, cy, bw, bh = box.xywhn[0].tolist()
            lines.append(f"{cls_id} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")
    return yolo_lines_to_boxes(lines)


def default_proposal_runner(image_path: Path, conf: float = PROPOSAL_CONF) -> list[Box]:
    model = get_proposal_model()
    if _proposal_backend and _proposal_backend.startswith("ultralytics:"):
        return ultralytics_boxes(model, image_path, conf)
    from pseudo_label import pseudo_label_image

    model.conf = conf
    lines, _, _ = pseudo_label_image(
        model,
        image_path,
        model_class_names(),
        640,
        include_deprecated=False,
    )
    return yolo_lines_to_boxes(lines)


class LabelSession:
    def __init__(
        self,
        *,
        images: list[Path] | None = None,
        regression_dir: Path | None = None,
        labels_dir: Path | None = None,
    ) -> None:
        self.regression_dir = regression_dir or REGRESSION_DIR
        self.labels_dir = labels_dir or (self.regression_dir / "labels")
        self.model_names = model_class_names()
        self.class_names = _load_class_names()
        self.images = images if images is not None else [p for p in CORE_IMAGES if p.is_file()]
        if not self.images:
            raise FileNotFoundError("Keine Queue-Bilder gefunden")
        self.index = 0
        self.box_cache: dict[str, list[Box]] = {}
        self.proposal_cache: dict[str, list[Box]] = {}
        self.boxes: list[Box] = []
        self.proposals: list[Box] = []
        self.display_size: tuple[int, int] = (1, 1)
        self._load_boxes_for_current()

    def _rel_image_path(self, image_path: Path | None = None) -> str:
        path = image_path or self._current_image()
        return str(path.relative_to(self.regression_dir))

    def _label_path_for(self, image_path: Path | None = None) -> Path:
        rel = Path(self._rel_image_path(image_path)).with_suffix(".txt")
        return self.labels_dir / rel

    def _current_image(self) -> Path:
        return self.images[self.index]

    def _cache_current(self) -> None:
        rel = self._rel_image_path()
        self.box_cache[rel] = list(self.boxes)
        self.proposal_cache[rel] = list(self.proposals)

    def _load_boxes_for_current(self) -> None:
        rel = self._rel_image_path()
        if rel in self.box_cache:
            self.boxes = list(self.box_cache[rel])
        else:
            self.boxes = _read_yolo_boxes(self._label_path_for())
        self.proposals = list(self.proposal_cache.get(rel, []))
        with Image.open(self._current_image()) as img:
            _, self.display_size = _resize_for_display(img.convert("RGB"))

    def _box_row(self, idx: int, box: Box, *, proposed: bool) -> dict:
        cls_id, cx, cy, w, h = box
        return {
            "index": idx,
            "cls_id": cls_id,
            "name": _class_name(cls_id, self.model_names),
            "cx": cx,
            "cy": cy,
            "w": w,
            "h": h,
            "color": PROPOSAL_COLOR if proposed else BOX_COLORS[cls_id % len(BOX_COLORS)],
            "proposed": proposed,
        }

    def to_state(self) -> dict:
        rel = self._rel_image_path()
        label_path = self._label_path_for()
        box_rows = [self._box_row(idx, box, proposed=False) for idx, box in enumerate(self.boxes, start=1)]
        proposal_rows = [self._box_row(idx, box, proposed=True) for idx, box in enumerate(self.proposals, start=1)]
        try:
            label_rel = str(label_path.relative_to(self.regression_dir))
        except ValueError:
            label_rel = str(label_path)
        return {
            "index": self.index,
            "total": len(self.images),
            "rel_path": rel,
            "display_width": self.display_size[0],
            "display_height": self.display_size[1],
            "classes": self.class_names,
            "legend": [
                {"id": self.model_names.index(n), "name": n}
                for n in self.class_names
                if n in self.model_names
            ],
            "boxes": box_rows,
            "proposals": proposal_rows,
            "proposal_conf": PROPOSAL_CONF,
            "saved": label_path.is_file(),
            "label_rel": label_rel,
        }

    def render_image_bytes(self) -> bytes:
        with Image.open(self._current_image()) as source:
            display, self.display_size = _resize_for_display(source.convert("RGB"))
        buf = io.BytesIO()
        display.save(buf, format="PNG")
        return buf.getvalue()

    def add_box(self, class_name: str, x1: float, y1: float, x2: float, y2: float) -> None:
        box = _box_from_display_rect(x1, y1, x2, y2, self.display_size, class_name, self.model_names)
        if box is None:
            raise ValueError("Ungültige Box oder Klasse")
        self.boxes.append(box)
        self._cache_current()

    def remove_last(self) -> None:
        if self.boxes:
            self.boxes.pop()
            self._cache_current()

    def delete_item(self, kind: str, index: int) -> None:
        target = self.proposals if kind == "proposal" else self.boxes
        if index < 0 or index >= len(target):
            raise ValueError("Ungültiger Box-Index")
        target.pop(index)
        self._cache_current()

    def accept_all_proposals(self) -> None:
        self.boxes.extend(self.proposals)
        self.proposals = []
        self._cache_current()

    def load_proposals(self, runner=None, conf: float = PROPOSAL_CONF) -> None:
        run = runner or default_proposal_runner
        raw = run(self._current_image(), conf)
        self.proposals = filter_proposal_boxes(raw)
        self._cache_current()

    def save_current(self) -> None:
        _write_yolo_boxes(self._label_path_for(), self.boxes)
        self._cache_current()

    def save_and_next(self) -> None:
        self.save_current()
        if self.index < len(self.images) - 1:
            self.index += 1
            self._load_boxes_for_current()

    def prev_image(self) -> None:
        if self.index > 0:
            self._cache_current()
            self.index -= 1
            self._load_boxes_for_current()

    def next_image(self) -> None:
        if self.index < len(self.images) - 1:
            self._cache_current()
            self.index += 1
            self._load_boxes_for_current()


session = LabelSession()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Lazy-load proposals on first "Vorschläge laden" so we do not steal MPS from an in-flight train.
    yield


app = FastAPI(title="CoC Manuelles Labeling", lifespan=lifespan)


class AddBoxRequest(BaseModel):
    class_name: str
    x1: float
    y1: float
    x2: float
    y2: float


class NavRequest(BaseModel):
    direction: str = Field(pattern="^(prev|next)$")


class DeleteItemRequest(BaseModel):
    kind: str = Field(pattern="^(box|proposal)$")
    index: int


HTML_PAGE = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CoC Manuelles Labeling</title>
<style>
  :root {
    color-scheme: light dark;
    --bg: #0f1117;
    --panel: #1a1d27;
    --text: #e8eaed;
    --muted: #9aa0a6;
    --accent: #8ab4f8;
    --border: #3c4043;
    --danger: #f28b82;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.5;
  }
  .wrap { max-width: 1280px; margin: 0 auto; padding: 1.25rem; }
  h1 { margin: 0 0 0.5rem; font-size: 1.5rem; }
  .intro { color: var(--muted); margin-bottom: 1rem; }
  .legend { font-size: 0.85rem; color: var(--muted); margin-bottom: 1rem; }
  .canvas-wrap {
    position: relative;
    display: inline-block;
    max-width: 100%;
    border: 1px solid var(--border);
    border-radius: 8px;
    overflow: hidden;
    background: #000;
    cursor: crosshair;
  }
  canvas { display: block; max-width: 100%; height: auto; }
  .toolbar, .actions { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; margin: 1rem 0; }
  select, button {
    font: inherit;
    padding: 0.45rem 0.75rem;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--panel);
    color: var(--text);
  }
  button { cursor: pointer; }
  button.primary { background: #1a73e8; border-color: #1a73e8; color: #fff; }
  button.danger { color: var(--danger); }
  button.proposal { background: #c2640a; border-color: #c2640a; color: #fff; }
  button:disabled { opacity: 0.5; cursor: not-allowed; }
  .meta { margin: 0.75rem 0; }
  .meta strong { color: var(--accent); }
  .box-list { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 0.75rem 1rem; min-height: 3rem; }
  .box-list li { margin: 0.25rem 0; font-family: ui-monospace, monospace; font-size: 0.9rem; }
  .box-list li.proposed { color: #ffb366; }
  .box-list li.selected { outline: 1px solid var(--accent); }
  .empty { color: var(--muted); font-style: italic; }
  .hint { color: var(--muted); font-size: 0.9rem; margin-top: 0.5rem; }
  .status.saved { color: #81c995; }
  .status.unsaved { color: #fdd663; }
</style>
</head>
<body>
<div class="wrap">
  <h1>Manuelles Labeling — Regression-Set</h1>
  <p class="intro">
    YOLO-Boxen per <strong>Mausziehen</strong> setzen. Optional
    <strong>Vorschläge laden</strong> (fine-tuned YOLO auf CPU, conf 0.25, ohne Hero-Pads) —
    gestrichelte orange Boxen prüfen, <strong>Alle übernehmen</strong> oder
    einzelne per Klick + Entf löschen. Speichern schreibt nur bestätigte Boxen
    nach <code>labels/th17/</code> bzw. <code>labels/th18/</code> (bzw. th15/th16).
  </p>
  <div class="legend" id="legend"></div>

  <div class="canvas-wrap">
    <canvas id="canvas"></canvas>
  </div>
  <p class="hint">Tipp: kurzer Klick wählt eine Box; Escape bricht eine angefangene Box ab; Entf löscht die Auswahl.</p>

  <div class="toolbar">
    <label for="class-select">Klasse:</label>
    <select id="class-select"></select>
  </div>

  <div class="actions">
    <button type="button" id="btn-propose" class="proposal">Vorschläge laden</button>
    <button type="button" id="btn-accept">Alle übernehmen</button>
    <button type="button" id="btn-delete-sel" class="danger">Auswahl löschen</button>
    <button type="button" id="btn-remove" class="danger">Letzte löschen</button>
    <button type="button" id="btn-prev">Zurück</button>
    <button type="button" id="btn-next">Weiter</button>
    <button type="button" id="btn-save">Speichern</button>
    <button type="button" id="btn-save-next" class="primary">Speichern &amp; Weiter</button>
  </div>

  <div class="meta" id="progress"></div>
  <div class="meta" id="status"></div>
  <div class="box-list" id="box-list"></div>
</div>
<script>
const canvas = document.getElementById("canvas");
const ctx = canvas.getContext("2d");
const classSelect = document.getElementById("class-select");
const progressEl = document.getElementById("progress");
const statusEl = document.getElementById("status");
const boxListEl = document.getElementById("box-list");
const legendEl = document.getElementById("legend");

let state = null;
let img = new Image();
let dragging = false;
let dragStart = null;
let previewRect = null;
let selected = null;

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  if (res.status === 204) return null;
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) return res.json();
  return res;
}

function canvasCoords(evt) {
  const rect = canvas.getBoundingClientRect();
  const scaleX = canvas.width / rect.width;
  const scaleY = canvas.height / rect.height;
  return {
    x: (evt.clientX - rect.left) * scaleX,
    y: (evt.clientY - rect.top) * scaleY,
  };
}

function yoloToRect(box) {
  const w = state.display_width;
  const h = state.display_height;
  const bw = box.w * w;
  const bh = box.h * h;
  const x = box.cx * w - bw / 2;
  const y = box.cy * h - bh / 2;
  return { x, y, w: bw, h: bh };
}

function drawBox(rect, color, label, dashed = false, highlight = false) {
  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth = highlight ? 4 : 2;
  if (dashed) ctx.setLineDash([6, 4]);
  ctx.strokeRect(rect.x, rect.y, rect.w, rect.h);
  if (highlight) {
    ctx.setLineDash([]);
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 1;
    ctx.strokeRect(rect.x - 2, rect.y - 2, rect.w + 4, rect.h + 4);
  }
  if (label) {
    ctx.fillStyle = color;
    ctx.font = "14px sans-serif";
    ctx.fillText(label, rect.x + 3, Math.max(rect.y - 4, 14));
  }
  ctx.restore();
}

function isSelected(kind, idx0) {
  return selected && selected.kind === kind && selected.index === idx0;
}

function redraw() {
  if (!img.complete || !state) return;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(img, 0, 0);
  (state.boxes || []).forEach((box, i) => {
    drawBox(yoloToRect(box), box.color, box.name, false, isSelected("box", i));
  });
  (state.proposals || []).forEach((box, i) => {
    drawBox(yoloToRect(box), box.color || "#ff8800", box.name, true, isSelected("proposal", i));
  });
  if (previewRect) {
    drawBox(previewRect, "#00ff88", classSelect.value, true);
  }
}

function hitTest(x, y) {
  const lists = [
    ["proposal", state.proposals || []],
    ["box", state.boxes || []],
  ];
  for (const [kind, items] of lists) {
    for (let i = items.length - 1; i >= 0; i--) {
      const r = yoloToRect(items[i]);
      if (x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h) {
        return { kind, index: i };
      }
    }
  }
  return null;
}

function renderMeta() {
  const nProp = (state.proposals || []).length;
  progressEl.innerHTML = `<strong>Bild ${state.index + 1}/${state.total}</strong> — <code>${state.rel_path}</code> — ${state.boxes.length} Boxen` +
    (nProp ? ` · ${nProp} Vorschläge (conf≥${state.proposal_conf})` : "");
  const cls = state.saved ? "saved" : "unsaved";
  const txt = state.saved ? "gespeichert" : "noch nicht gespeichert";
  statusEl.innerHTML = `<span class="status ${cls}">Label-Datei: <code>${state.label_rel}</code> (${txt})</span>`;
  const rows = [];
  (state.boxes || []).forEach((b, i) => {
    const sel = isSelected("box", i) ? " selected" : "";
    rows.push(`<li class="${sel}" data-kind="box" data-index="${i}">${b.index}. <strong>${b.name}</strong> (id ${b.cls_id}) — bestätigt</li>`);
  });
  (state.proposals || []).forEach((b, i) => {
    const sel = isSelected("proposal", i) ? " selected" : "";
    rows.push(`<li class="proposed${sel}" data-kind="proposal" data-index="${i}">V${b.index}. <strong>${b.name}</strong> (id ${b.cls_id}) — Vorschlag</li>`);
  });
  if (rows.length === 0) {
    boxListEl.innerHTML = '<span class="empty">Keine Boxen — ziehen zum Zeichnen oder „Vorschläge laden“.</span>';
  } else {
    boxListEl.innerHTML = "<ul>" + rows.join("") + "</ul>";
    boxListEl.querySelectorAll("li[data-kind]").forEach((li) => {
      li.addEventListener("click", () => {
        selected = { kind: li.dataset.kind, index: Number(li.dataset.index) };
        renderMeta();
        redraw();
      });
    });
  }
  document.getElementById("btn-prev").disabled = state.index === 0;
  document.getElementById("btn-next").disabled = state.index >= state.total - 1;
  document.getElementById("btn-accept").disabled = nProp === 0;
  document.getElementById("btn-delete-sel").disabled = !selected;
}

function renderLegend() {
  legendEl.textContent = "Aktive Klassen: " + state.legend.map(x => `${x.id}:${x.name}`).join(" · ");
}

function renderClasses() {
  const current = classSelect.value;
  classSelect.innerHTML = state.classes.map(c => `<option value="${c}">${c}</option>`).join("");
  if (current && state.classes.includes(current)) classSelect.value = current;
}

async function loadImage() {
  const res = await fetch("/api/image");
  if (!res.ok) throw new Error("Bild konnte nicht geladen werden");
  const blob = await res.blob();
  img = new Image();
  await new Promise((resolve, reject) => {
    img.onload = resolve;
    img.onerror = reject;
    img.src = URL.createObjectURL(blob);
  });
  canvas.width = state.display_width;
  canvas.height = state.display_height;
  redraw();
}

async function refresh() {
  state = await api("/api/state");
  selected = null;
  renderClasses();
  renderLegend();
  renderMeta();
  await loadImage();
}

canvas.addEventListener("mousedown", (evt) => {
  if (evt.button !== 0) return;
  dragging = true;
  dragStart = canvasCoords(evt);
  previewRect = null;
});

canvas.addEventListener("mousemove", (evt) => {
  if (!dragging || !dragStart) return;
  const p = canvasCoords(evt);
  const x = Math.min(dragStart.x, p.x);
  const y = Math.min(dragStart.y, p.y);
  const w = Math.abs(p.x - dragStart.x);
  const h = Math.abs(p.y - dragStart.y);
  previewRect = { x, y, w, h };
  redraw();
});

canvas.addEventListener("mouseup", async (evt) => {
  if (!dragging || !dragStart) return;
  dragging = false;
  const p = canvasCoords(evt);
  const dist = Math.hypot(p.x - dragStart.x, p.y - dragStart.y);
  previewRect = null;
  if (dist < 5) {
    selected = hitTest(p.x, p.y);
    renderMeta();
    redraw();
    dragStart = null;
    return;
  }
  try {
    state = await api("/api/box", {
      method: "POST",
      body: JSON.stringify({
        class_name: classSelect.value,
        x1: dragStart.x,
        y1: dragStart.y,
        x2: p.x,
        y2: p.y,
      }),
    });
    selected = null;
    renderMeta();
    redraw();
  } catch (e) {
    alert(e.message);
    redraw();
  }
  dragStart = null;
});

canvas.addEventListener("mouseleave", () => {
  if (dragging) {
    dragging = false;
    dragStart = null;
    previewRect = null;
    redraw();
  }
});

async function deleteSelected() {
  if (!selected) return;
  state = await api("/api/delete-item", {
    method: "POST",
    body: JSON.stringify(selected),
  });
  selected = null;
  renderMeta();
  redraw();
}

document.addEventListener("keydown", (evt) => {
  if (evt.key === "Escape" && dragging) {
    dragging = false;
    dragStart = null;
    previewRect = null;
    redraw();
  }
  if ((evt.key === "Delete" || evt.key === "Backspace") && selected && !dragging) {
    evt.preventDefault();
    deleteSelected();
  }
});

document.getElementById("btn-propose").addEventListener("click", async () => {
  const btn = document.getElementById("btn-propose");
  btn.disabled = true;
  btn.textContent = "Lade Vorschläge…";
  try {
    state = await api("/api/proposals", { method: "POST" });
    selected = null;
    renderMeta();
    redraw();
  } catch (e) {
    alert(e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Vorschläge laden";
  }
});

document.getElementById("btn-accept").addEventListener("click", async () => {
  state = await api("/api/proposals/accept", { method: "POST" });
  selected = null;
  renderMeta();
  redraw();
});

document.getElementById("btn-delete-sel").addEventListener("click", deleteSelected);

document.getElementById("btn-remove").addEventListener("click", async () => {
  state = await api("/api/box/last", { method: "DELETE" });
  selected = null;
  renderMeta();
  redraw();
});

document.getElementById("btn-save").addEventListener("click", async () => {
  state = await api("/api/save", { method: "POST" });
  renderMeta();
});

document.getElementById("btn-save-next").addEventListener("click", async () => {
  state = await api("/api/save-next", { method: "POST" });
  selected = null;
  renderLegend();
  renderMeta();
  await loadImage();
});

document.getElementById("btn-prev").addEventListener("click", async () => {
  state = await api("/api/nav", { method: "POST", body: JSON.stringify({ direction: "prev" }) });
  selected = null;
  renderLegend();
  renderMeta();
  await loadImage();
});

document.getElementById("btn-next").addEventListener("click", async () => {
  state = await api("/api/nav", { method: "POST", body: JSON.stringify({ direction: "next" }) });
  selected = null;
  renderLegend();
  renderMeta();
  await loadImage();
});

refresh().catch(err => {
  document.body.innerHTML = `<div class="wrap"><h1>Fehler</h1><p>${err.message}</p></div>`;
});
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return HTML_PAGE


@app.get("/api/state")
def get_state() -> dict:
    return session.to_state()


@app.get("/api/image")
def get_image() -> Response:
    return Response(content=session.render_image_bytes(), media_type="image/png")


@app.post("/api/box")
def add_box(req: AddBoxRequest) -> dict:
    try:
        session.add_box(req.class_name, req.x1, req.y1, req.x2, req.y2)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return session.to_state()


@app.delete("/api/box/last")
def remove_last_box() -> dict:
    session.remove_last()
    return session.to_state()


@app.post("/api/delete-item")
def delete_item(req: DeleteItemRequest) -> dict:
    try:
        session.delete_item(req.kind, req.index)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return session.to_state()


@app.post("/api/proposals")
def load_proposals() -> dict:
    try:
        session.load_proposals()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Vorschläge fehlgeschlagen: {exc}") from exc
    return session.to_state()


@app.post("/api/proposals/accept")
def accept_proposals() -> dict:
    session.accept_all_proposals()
    return session.to_state()


@app.post("/api/save")
def save_current() -> dict:
    session.save_current()
    return session.to_state()


@app.post("/api/save-next")
def save_and_next() -> dict:
    session.save_and_next()
    return session.to_state()


@app.post("/api/nav")
def navigate(req: NavRequest) -> dict:
    if req.direction == "prev":
        session.prev_image()
    else:
        session.next_image()
    return session.to_state()


def resolve_image_queue(queue: str, extra_images: list[Path]) -> list[Path]:
    if extra_images:
        resolved = []
        for path in extra_images:
            path = path.expanduser().resolve()
            if not path.is_file():
                raise FileNotFoundError(f"Bild nicht gefunden: {path}")
            resolved.append(path)
        return resolved
    source = UNLABELED_QUEUE if queue == "unlabeled" else CORE_IMAGES
    found = [p for p in source if p.is_file()]
    if not found:
        raise FileNotFoundError(f"Keine Bilder für Queue {queue!r}")
    return found


def write_prefill_drafts(images: list[Path], conf: float = PROPOSAL_CONF) -> list[Path]:
    """Write draft YOLO txts under labels/ only when no label file exists yet."""
    written: list[Path] = []
    pending: list[Path] = []
    for image_path in images:
        label_path = _label_path_for(image_path)
        if label_path.is_file():
            logging.info("prefill skip (exists): %s", label_path)
            continue
        pending.append(image_path)
    if not pending:
        return written
    get_proposal_model()
    for image_path in pending:
        boxes = filter_proposal_boxes(default_proposal_runner(image_path, conf))
        label_path = _label_path_for(image_path)
        _write_yolo_boxes(label_path, boxes)
        written.append(label_path)
        logging.info("prefill %d boxes → %s", len(boxes), label_path)
    return written


def main() -> int:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="FastAPI canvas labeler for CoC regression screenshots.")
    parser.add_argument(
        "--queue",
        choices=("core", "unlabeled"),
        default="core",
        help="core = 4 labeled war bases; unlabeled = 5 new TH17/TH18 screenshots",
    )
    parser.add_argument(
        "images",
        nargs="*",
        type=Path,
        help="Optional explicit image paths (overrides --queue)",
    )
    parser.add_argument(
        "--prefill",
        action="store_true",
        help="Write draft YOLO labels from latest idle weights (skip files that already exist)",
    )
    args = parser.parse_args()
    images = resolve_image_queue(args.queue, args.images)
    if args.prefill:
        write_prefill_drafts(images)

    global session
    session = LabelSession(images=images)
    print(f"\nÖffne http://127.0.0.1:{PORT}")
    print(f"Queue: {len(images)} Bilder — " + ", ".join(p.name for p in images))
    print("Speichern / Speichern & Weiter schreibt nach labels/<th>/")
    print("Tasten: Escape = Box abbrechen, Entf/Backspace = Auswahl löschen. Keine Zahlen-Shortcuts für Klassen.\n")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
