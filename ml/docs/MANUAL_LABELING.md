# Manuelles Labeling — Regression-Set

Kurzanleitung zum manuellen Annotieren der 4 Kern-War-Bases (TH15/TH16) im YOLO-Format.

## Empfohlen: Browser-App (Gradio)

**labelImg** (PyQt5) stürzt unter Python 3.14 und auch unter 3.12 beim Scrollen/Zoomen ab (`TypeError: setValue … float`). Statt labelImg-Patches nutzen wir die **browserbasierte Label-App** im Haupt-venv:

```bash
cd coc-base-analyzer/ml
./scripts/run_manual_label.sh
```

Öffne **http://127.0.0.1:8766**

### Ablauf in der App

1. Großes Bild mit **Bounding-Box-Editor** — Rechteck per **Maus ziehen** (click-drag) oder zwei Klicks zeichnen, wie in labelImg
2. **Klasse** im Dropdown wählen (12 Klassen aus `classes.txt`)
3. Rechteck auf dem Bild aufziehen, dann **Box übernehmen** — Box erscheint in der Liste und in der Vorschau
4. Boxen im Editor anklicken, verschieben oder an den Ecken skalieren; **Letzte löschen** entfernt die zuletzt gespeicherte Box
5. **Speichern** schreibt die `.txt`-Datei; **Speichern & Weiter** speichert und geht zum nächsten Bild
6. **Zurück / Weiter** navigiert zwischen den 4 Kern-Bildern (Änderungen bleiben im Speicher bis Speichern)

**Klassen:** Dropdown aus `classes.txt` — 12 aktive Klassen, keine Hero-Pads (`kingpad`, `queenpad`, `rcpad`, `wardenpad`).

**Technik:** `gradio-image-annotation` — kein manuelles Einstellen von Koordinaten-Slidern mehr nötig.

## labelImg (veraltet)

| Option | Status |
|--------|--------|
| **Gradio `manual_label_app.py`** | **Empfohlen** |
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

```bash
cd coc-base-analyzer/data-pipeline

.venv/bin/python -m dataset.build_dataset \
  --output datasets/processed/yolo_v1 \
  --include-demo \
  --include-regression \
  --manual-labels-only
```

`--manual-labels-only`:

- nutzt nur vorhandene `.txt`-Dateien unter `labels/<rel_path>.txt`
- ignoriert Pseudo-Label-Metadaten
- mappt Klassen-Indizes aus `classes.txt` (aktive Klassen) auf die Keremberke-Modell-Indizes (0–15)

Ohne manuelle Labels werden die 4 War-Bases als unlabeled unter `images_unlabeled/` abgelegt.

## Tipps

- Rathaus (`th13`) = visuell TH15/TH16, im Baseline-Modell heißt die Klasse noch `th13`
- Monolith, Spell Tower etc. sind **noch keine Klassen** — nicht labeln
- Bei Unsicherheit: Box weglassen statt raten

## Verwandte Tools

- **Pseudo-Label Review:** `python scripts/label_review_app.py` → http://127.0.0.1:8765
