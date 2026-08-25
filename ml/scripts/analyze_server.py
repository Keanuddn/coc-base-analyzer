#!/usr/bin/env python3
"""Local screenshot → detection JSON (same payload as infer.py).

Not an attack planner. Fan-content: user screenshot in, labels out.

Run:
    cd ml && ./scripts/run_analyze.sh
    Open http://127.0.0.1:8767
"""

from __future__ import annotations

import argparse
import base64
import logging
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse

ML_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ML_ROOT / "src"))

PORT = 8767
DEFAULT_WEIGHTS = ML_ROOT / "runs" / "coc_yolo_v9" / "weights" / "best.pt"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}

HTML_PAGE = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>CoC Base Analyzer</title>
<style>
  :root { color-scheme: dark; }
  body { font-family: ui-sans-serif, system-ui, sans-serif; margin: 0; background: #111; color: #eee; }
  .wrap { max-width: 960px; margin: 0 auto; padding: 1.5rem; }
  h1 { font-size: 1.25rem; font-weight: 600; }
  p.note { color: #aaa; font-size: 0.9rem; }
  form { display: flex; flex-wrap: wrap; gap: 0.75rem; align-items: end; margin: 1rem 0; }
  label { display: flex; flex-direction: column; gap: 0.25rem; font-size: 0.85rem; color: #ccc; }
  input, button { font: inherit; padding: 0.4rem 0.6rem; border-radius: 6px; border: 1px solid #444; background: #1c1c1c; color: #eee; }
  button { cursor: pointer; background: #2a6; border-color: #2a6; color: #111; font-weight: 600; }
  button:disabled { opacity: 0.5; cursor: wait; }
  #err { color: #f66; white-space: pre-wrap; }
  table { border-collapse: collapse; width: 100%; font-size: 0.85rem; }
  th, td { text-align: left; padding: 0.35rem 0.5rem; border-bottom: 1px solid #333; }
  .pill { display: inline-block; margin-right: 0.5rem; background: #222; padding: 0.25rem 0.5rem; border-radius: 999px; }
  .pill.over { background: #422; color: #f88; }
  tr.over td { color: #f66; font-weight: 600; }
  img.overlay { max-width: 100%; height: auto; border: 1px solid #333; margin: 0.75rem 0; }
</style>
</head>
<body>
<div class="wrap">
  <h1>Clash of Clans Base Analyzer</h1>
  <p class="note">Inoffizielles Fan-Tool. Screenshot hochladen → Bild mit Kästchen + Gebäudeliste. Kein Angriffsplan, keine erfundenen Stats.</p>
  <form id="f">
    <label>Screenshot
      <input type="file" name="image" accept="image/png,image/jpeg,image/webp" required/>
    </label>
    <label>TH (optional)
      <input type="number" name="th" min="14" max="18" placeholder="auto"/>
    </label>
    <button type="submit">Analysieren</button>
  </form>
  <p id="err"></p>
  <div id="out"></div>
</div>
<script>
const f = document.getElementById("f");
const err = document.getElementById("err");
const out = document.getElementById("out");
f.addEventListener("submit", async (e) => {
  e.preventDefault();
  err.textContent = "";
  out.innerHTML = "läuft… erstes Mal kann dauern (Modell-Load).";
  const btn = f.querySelector("button");
  btn.disabled = true;
  try {
    const body = new FormData(f);
    const res = await fetch("/analyze", { method: "POST", body });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || res.statusText);
    const s = data.summary || {};
    const t = (s.defenses_targeting) || {};
    const gate = data.count_gate || {};
    const over = gate.over_max || [];
    const gateRows = gate.rows || [];
    let table;
    if (gateRows.length) {
      const body = gateRows.map(r => {
        const cls = r.status === "over" ? "over" : "";
        const max = r.wiki_max == null ? "—" : r.wiki_max;
        const note = r.merge_cap && r.status === "over" ? " *" : "";
        return `<tr class="${cls}"><td>${r.class}${note}</td><td>${r.detected}</td><td>${max}</td></tr>`;
      }).join("");
      table = `<table><thead><tr><th>Klasse</th><th>Erkannt</th><th>Wiki-Max</th></tr></thead><tbody>${body}</tbody></table>`;
    } else {
      const counts = s.by_class || s.counts || {};
      const body = Object.entries(counts).sort((a,b) => b[1]-a[1])
        .map(([k,v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("");
      table = `<table><thead><tr><th>Klasse</th><th>Anzahl</th></tr></thead><tbody>${body}</tbody></table>`;
    }
    const overPill = over.length
      ? `<span class="pill over">${over.length} über Wiki-Max</span>`
      : "";
    const mergeNote = gateRows.some(r => r.merge_cap && r.status === "over")
      ? `<p class="note">* Wiki-Max nach Pflicht-Merges. Ungemergte Gebäude können darüber liegen.</p>`
      : "";
    const th = data.town_hall ?? data.th_gate?.th ?? "—";
    const src = data.town_hall_source || data.th_gate?.source || "—";
    const overlay = data.overlay_jpeg_base64
      ? `<p class="note">Kästchen = erkannt. Fehlt ein Gebäude im Bild, hat das Modell es verpasst. Falsches Label = Verwechslung. Rot in der Tabelle = mehr erkannt als Wiki-Maximum.</p>
         <img class="overlay" alt="Erkennungen auf dem Screenshot" src="data:image/jpeg;base64,${data.overlay_jpeg_base64}"/>`
      : `<p class="note">Kein Overlay erzeugt.</p>`;
    const dump = {...data};
    delete dump.overlay_jpeg_base64;
    out.innerHTML = `
      ${overlay}
      <p>
        <span class="pill">TH ${th} (${src})</span>
        <span class="pill">air ${t.air ?? 0}</span>
        <span class="pill">ground ${t.ground ?? 0}</span>
        <span class="pill">both ${t.both ?? 0}</span>
        <span class="pill">unknown ${t.unknown ?? 0}</span>
        ${overPill}
      </p>
      <p class="note">${(data.th_gate && data.th_gate.notes && data.th_gate.notes[0]) || ""}</p>
      ${table}
      ${mergeNote}
      <details><summary>Roh-JSON</summary><pre>${JSON.stringify(dump, null, 2)}</pre></details>
    `;
  } catch (ex) {
    err.textContent = String(ex.message || ex);
    out.innerHTML = "";
  } finally {
    btn.disabled = false;
  }
});
</script>
</body>
</html>
"""

InferFn = Callable[..., dict[str, Any]]


def create_app(
    *,
    weights: Path | None = None,
    infer_fn: InferFn | None = None,
) -> FastAPI:
    weights_path = Path(weights) if weights else DEFAULT_WEIGHTS
    if infer_fn is None:
        from infer import run_inference as runner
    else:
        runner = infer_fn

    app = FastAPI(title="CoC Base Analyzer", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return HTML_PAGE

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/analyze")
    async def analyze(
        image: UploadFile = File(...),
        th: str | None = Form(default=None),
    ) -> dict[str, Any]:
        suffix = Path(image.filename or "upload.png").suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise HTTPException(status_code=400, detail="Nur PNG, JPEG oder WebP.")
        raw = await image.read()
        if not raw:
            raise HTTPException(status_code=400, detail="Leere Datei.")
        if len(raw) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Datei zu groß (max 20 MB).")

        th_int: int | None = None
        if th is not None and str(th).strip():
            try:
                th_int = int(str(th).strip())
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="TH muss eine Zahl sein.") from exc
            if th_int < 14 or th_int > 18:
                raise HTTPException(status_code=400, detail="TH nur 14–18, sonst leer lassen.")

        if infer_fn is None and not weights_path.is_file():
            raise HTTPException(
                status_code=503,
                detail=f"Gewichte fehlen: {weights_path}",
            )

        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            image_path = work / f"upload{suffix}"
            overlay_path = work / "overlay.jpg"
            image_path.write_bytes(raw)
            try:
                result = runner(
                    image_path,
                    weights=weights_path,
                    conf=0.25,
                    town_hall=th_int,
                    overlay_path=overlay_path,
                )
            except Exception as exc:  # noqa: BLE001
                logging.exception("analyze failed")
                raise HTTPException(status_code=500, detail=str(exc)) from exc
            payload = dict(result)
            if overlay_path.is_file() and overlay_path.stat().st_size > 0:
                payload["overlay_jpeg_base64"] = base64.b64encode(
                    overlay_path.read_bytes()
                ).decode("ascii")
            return payload

    return app


app = create_app()


def main() -> None:
    parser = argparse.ArgumentParser(description="Local CoC screenshot analyzer")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS)
    args = parser.parse_args()
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(
        create_app(weights=args.weights),
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
