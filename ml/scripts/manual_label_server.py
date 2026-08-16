#!/usr/bin/env python3
"""Browser-based manual YOLO labeling — FastAPI + canvas (no Gradio).

Run:
    cd ml && ./scripts/run_manual_label.sh
    Open http://127.0.0.1:8766
"""

from __future__ import annotations

import io
import logging
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from PIL import Image
from pydantic import BaseModel, Field

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

    def to_state(self) -> dict:
        rel = _rel_image_path(self._current_image())
        label_path = _label_path_for(self._current_image())
        box_rows = []
        for idx, (cls_id, cx, cy, w, h) in enumerate(self.boxes, start=1):
            name = _class_name(cls_id, self.model_names)
            box_rows.append(
                {
                    "index": idx,
                    "cls_id": cls_id,
                    "name": name,
                    "cx": cx,
                    "cy": cy,
                    "w": w,
                    "h": h,
                    "color": BOX_COLORS[cls_id % len(BOX_COLORS)],
                }
            )
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
            "saved": label_path.is_file(),
            "label_rel": str(label_path.relative_to(REGRESSION_DIR)),
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

    def save_current(self) -> None:
        _write_yolo_boxes(_label_path_for(self._current_image()), self.boxes)
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
app = FastAPI(title="CoC Manuelles Labeling")


class AddBoxRequest(BaseModel):
    class_name: str
    x1: float
    y1: float
    x2: float
    y2: float


class NavRequest(BaseModel):
    direction: str = Field(pattern="^(prev|next)$")


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
  button:disabled { opacity: 0.5; cursor: not-allowed; }
  .meta { margin: 0.75rem 0; }
  .meta strong { color: var(--accent); }
  .box-list { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 0.75rem 1rem; min-height: 3rem; }
  .box-list li { margin: 0.25rem 0; font-family: ui-monospace, monospace; font-size: 0.9rem; }
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
    YOLO-Boxen per <strong>Mausziehen</strong> setzen: Klasse wählen, auf dem Bild
    <strong>ziehen</strong> (Maus gedrückt halten) — die Box wird beim Loslassen übernommen.
    Speichern schreibt <code>.txt</code> nach <code>labels/th15/</code> bzw. <code>labels/th16/</code>.
  </p>
  <div class="legend" id="legend"></div>

  <div class="canvas-wrap">
    <canvas id="canvas"></canvas>
  </div>
  <p class="hint">Tipp: Escape bricht eine angefangene Box ab.</p>

  <div class="toolbar">
    <label for="class-select">Klasse:</label>
    <select id="class-select"></select>
  </div>

  <div class="actions">
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

function drawBox(rect, color, label, dashed = false) {
  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  if (dashed) ctx.setLineDash([6, 4]);
  ctx.strokeRect(rect.x, rect.y, rect.w, rect.h);
  if (label) {
    ctx.fillStyle = color;
    ctx.font = "14px sans-serif";
    ctx.fillText(label, rect.x + 3, Math.max(rect.y - 4, 14));
  }
  ctx.restore();
}

function redraw() {
  if (!img.complete || !state) return;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(img, 0, 0);
  for (const box of state.boxes) {
    drawBox(yoloToRect(box), box.color, box.name);
  }
  if (previewRect) {
    drawBox(previewRect, "#00ff88", classSelect.value, true);
  }
}

function renderMeta() {
  progressEl.innerHTML = `<strong>Bild ${state.index + 1}/${state.total}</strong> — <code>${state.rel_path}</code> — ${state.boxes.length} Boxen`;
  const cls = state.saved ? "saved" : "unsaved";
  const txt = state.saved ? "gespeichert" : "noch nicht gespeichert";
  statusEl.innerHTML = `<span class="status ${cls}">Label-Datei: <code>${state.label_rel}</code> (${txt})</span>`;
  if (state.boxes.length === 0) {
    boxListEl.innerHTML = '<span class="empty">Keine Boxen — auf dem Bild ziehen, um eine Box zu setzen.</span>';
  } else {
    boxListEl.innerHTML = "<ul>" + state.boxes.map(b =>
      `<li>${b.index}. <strong>${b.name}</strong> (id ${b.cls_id}) — cx=${b.cx.toFixed(4)}, cy=${b.cy.toFixed(4)}, w=${b.w.toFixed(4)}, h=${b.h.toFixed(4)}</li>`
    ).join("") + "</ul>";
  }
  document.getElementById("btn-prev").disabled = state.index === 0;
  document.getElementById("btn-next").disabled = state.index >= state.total - 1;
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
  previewRect = null;
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

document.addEventListener("keydown", (evt) => {
  if (evt.key === "Escape" && dragging) {
    dragging = false;
    dragStart = null;
    previewRect = null;
    redraw();
  }
});

document.getElementById("btn-remove").addEventListener("click", async () => {
  state = await api("/api/box/last", { method: "DELETE" });
  renderMeta();
  redraw();
});

document.getElementById("btn-save").addEventListener("click", async () => {
  state = await api("/api/save", { method: "POST" });
  renderMeta();
});

document.getElementById("btn-save-next").addEventListener("click", async () => {
  state = await api("/api/save-next", { method: "POST" });
  renderLegend();
  renderMeta();
  await loadImage();
});

document.getElementById("btn-prev").addEventListener("click", async () => {
  state = await api("/api/nav", { method: "POST", body: JSON.stringify({ direction: "prev" }) });
  renderLegend();
  renderMeta();
  await loadImage();
});

document.getElementById("btn-next").addEventListener("click", async () => {
  state = await api("/api/nav", { method: "POST", body: JSON.stringify({ direction: "next" }) });
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


def main() -> int:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print(f"\nÖffne http://127.0.0.1:{PORT}\n")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
