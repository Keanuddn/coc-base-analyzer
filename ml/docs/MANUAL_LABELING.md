# Manuelles Labeling — Regression-Set

Kurzanleitung zum manuellen Annotieren der 4 Kern-War-Bases (TH15/TH16) im YOLO-Format.

## Empfohlen: Browser-App (FastAPI + Canvas)

**labelImg** (PyQt5) stürzt unter Python 3.14 und auch unter 3.12 beim Scrollen/Zoomen ab (`TypeError: setValue … float`). Statt labelImg nutzen wir die **browserbasierte Label-App** im Haupt-venv — **ohne Gradio**, mit HTML-Canvas (Bilder laden zuverlässig):

```bash
cd coc-base-analyzer/ml
./scripts/run_manual_label.sh
```

Öffne **http://127.0.0.1:8766**

### Ablauf in der App

1. Optional **Vorschläge laden** — keremberke zeichnet gestrichelte orange Boxen (ohne Hero-Pads, conf 0.40)
2. Vorschläge prüfen: **Alle übernehmen**, oder einzelne per **Klick + Entf / Auswahl löschen** verwerfen
3. **Klasse** im Dropdown wählen und fehlende Boxen **ziehen**
4. **Escape** bricht eine angefangene Box ab; **Letzte löschen** entfernt die zuletzt gezeichnete Box
5. **Speichern** schreibt nur bestätigte Boxen in die `.txt`-Datei; **Speichern & Weiter** speichert und geht zum nächsten Bild
6. **Zurück / Weiter** navigiert zwischen den 4 Kern-Bildern (Änderungen bleiben im Speicher bis Speichern)

**Klassen:** Dropdown aus `classes.txt` — 12 aktive Klassen, keine Hero-Pads (`kingpad`, `queenpad`, `rcpad`, `wardenpad`).

### Automatisch vs. manuell

| Was | Automatisch? | Qualität |
|-----|--------------|----------|
| **Synthetische Renders** (`python -m dataset.generate_synthetic`) | Ja — Layout + YOLO-Boxen aus dem Isometric-Renderer | Hoch (perfekte Labels), aber **nicht** echte In-Game-Screenshots |
| **keremberke-Vorschläge** in dieser App (**Vorschläge laden**) | Halbautomatisch — Boxen vorschlagen, du bestätigst | Unzuverlässig auf TH15/16 (falsche Klassen, fehlende Gebäude). Hero-Pads werden gefiltert, conf=0.40 |
| **OpenLayout-Links** | Nein — enthalten keine Gebäudekoordinaten | — |
| **Echte War-Base-Screenshots** | Nein — weiterhin menschlich | Pflicht, wenn das Modell auf echten Fotos treffen soll |

100 % automatische Labels auf echten Screenshots sind **noch nicht** hochwertig. Workflow: Synthetik skalieren; in der App Vorschläge prüfen/löschen/ergänzen; speichern.

**Technik:** FastAPI liefert PNG-Bytes an einen HTML-Canvas (kein Gradio-Dateiserving). Bilder werden für die Anzeige auf max. 1200 px Breite skaliert; YOLO-Koordinaten bleiben korrekt normalisiert. Das keremberke-Modell wird einmal beim Serverstart geladen.

## labelImg (veraltet)

| Option | Status |
|--------|--------|
| **FastAPI `manual_label_server.py`** | **Empfohlen** |
| Gradio `manual_label_app.py` | Veraltet — Gradio `gr.Image` „Loading…“-Bug |
| labelImg + Python-3.12-venv + Patch | Veraltet — PyQt-Crashes, Whack-a-Mole |

Falls nötig (nicht empfohlen):

```bash
./scripts/run_labelimg.sh th15   # oder th16
```

## YOLO-Format

Pro Bild entsteht eine `.txt`-Datei gleichen Namens unter `labels/th15/` bzw. `labels/th16/`, z. B.:

```
labels/th15/war_base_illyrian_god.txt
```

Format pro Zeile (YOLO normalisiert, Modell-Indizes 0–15):

```
<class_index> <cx> <cy> <width> <height>
```

Beispiel:

```
3 0.322123 0.386599 0.034815 0.047809
8 0.409941 0.742560 0.026453 0.043646
```

## Welche Bilder labeln?

**4 Kern-War-Bases** (in der App fest eingebunden):

| TH | Datei |
|----|-------|
| TH15 | `th15/war_base_illyrian_god.png` |
| TH15 | `th15/war_base_cocbase_wizztower_ring.png` |
| TH16 | `th16/war_base_cocbase_volcanic_warmap.png` |
| TH16 | `th16/war_base_cocbase_sakura_scenery.png` |

`_extras/` und TH17/TH18 können später folgen.

## Pseudo-Labels

Alte Pseudo-Labels liegen unter `labels/_pseudo_backup/` — **nicht** für manuelles Labeling verwenden. Frische manuelle Labels gehören direkt nach `labels/th15/` bzw. `labels/th16/`.

## Dataset neu bauen (nach dem Labeling)

Synthetik erzeugen (Standard: 200 Layouts, gitignored unter `datasets/processed/synthetic_v1/`):

```bash
cd coc-base-analyzer/data-pipeline
.venv/bin/python -m dataset.generate_synthetic --count 200 --force
```

`--force` overwrites existing PNG+txt so village grass (not the old solid green) is on every
image. Omit `--force` to skip files that already exist. `--flat-background` restores the
legacy solid fill.

Dann YOLO-Datensatz bauen:

```bash
cd coc-base-analyzer/data-pipeline

.venv/bin/python -m dataset.build_dataset \
  --output datasets/processed/yolo_v1 \
  --include-demo \
  --include-regression \
  --manual-labels-only \
  --include-synthetic-bulk
```

`--manual-labels-only`:

- nutzt nur vorhandene `.txt`-Dateien unter `labels/<rel_path>.txt`
- ignoriert Pseudo-Label-Metadaten
- mappt Klassen-Indizes aus `classes.txt` (aktive Klassen) auf die Keremberke-Modell-Indizes (0–15)

Ohne manuelle Labels werden die 4 War-Bases als unlabeled unter `images_unlabeled/` abgelegt.

## First training pass (2026-08-16)

Incomplete manual labels were accepted for the first fine-tune (`arbeite damit erstmal`):

- **`th13` is Town Hall.** The name comes from the keremberke YOLOv5 head. There is no separate TH15/TH16 class; halls labeled with this slot are TH15/TH16 visually.
- **Dataset mixes TH15 and TH16** (2 core war bases each). That mix is expected for this pass.
- **Labels are incomplete** (forgotten buildings, no Town Hall boxes in the first 4 files). Source `.txt` files were not rewritten.
- Browser labeler writes **keremberke model indices** (0–15), not compact `classes.txt` 0–11 indices.

## Tipps

- Rathaus (`th13`) = visuell TH15/TH16, im Baseline-Modell heißt die Klasse noch `th13`
- Monolith, Spell Tower etc. sind **noch keine Klassen** — nicht labeln
- Bei Unsicherheit: Box weglassen statt raten

## Verwandte Tools

- **Pseudo-Label Review:** `python scripts/label_review_app.py` → http://127.0.0.1:8765
