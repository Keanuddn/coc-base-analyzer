# Manuelles Labeling — Regression-Set

Kurzanleitung zum manuellen Annotieren der 4 Kern-War-Bases (TH15/TH16) mit **labelImg** im YOLO-Format.

## Python 3.14 / macOS

Das `labelImg`-PyPI-Paket mit **PyQt5** stürzt unter **Python 3.14** (und beim Scrollen/Zoomen auch unter 3.12) ab:

```text
TypeError: setValue(self, a0: int): argument 1 has unexpected type 'float'
```

**Lösung:** labelImg in einem **eigenen Python-3.12-venv** ausführen (nicht `ml/.venv`). Das Startskript wendet automatisch einen Patch an (`scripts/patch_labelimg.py`), der `setValue`-Aufrufe auf `int()` castet (Scroll-/Zoom-Crash).

| Option | Status |
|--------|--------|
| Homebrew `brew install labelimg` | Nicht verfügbar (kein Formula/Cask) |
| **Dediziertes Python-3.12-venv + Auto-Patch** | **Empfohlen — getestet** |
| Gradio-App (Fallback) | Nur nötig, falls Patch fehlschlägt |

## labelImg starten (empfohlen)

```bash
brew install python@3.12   # falls python3.12 fehlt
cd coc-base-analyzer/ml
./scripts/run_labelimg.sh th15
# oder
./scripts/run_labelimg.sh th16
```

Beim ersten Start legt das Skript `.venv-labelimg` an, installiert labelImg/PyQt5 und patcht die `setValue`-Float-Bugs. Bei jedem weiteren Start wird der Patch idempotent geprüft.

Manuell (gleiche Umgebung):

```bash
brew install python@3.12
python3.12 -m venv ml/.venv-labelimg
ml/.venv-labelimg/bin/pip install setuptools labelImg PyQt5 lxml

cd ml/tests/regression_set
../../.venv-labelimg/bin/labelImg th15/ labels/th15/
# oder
../../.venv-labelimg/bin/labelImg th16/ labels/th16/
```

> `setuptools` liefert `distutils`, das labelImg 1.8.6 noch importiert.

In labelImg:

1. **Open Dir** → `th15/` oder `th16/` (wird oft schon per CLI gesetzt)
2. **Change Save Dir** → `labels/th15/` bzw. `labels/th16/`
3. **Format** → **YOLO** (nicht PascalVOC)
4. **View → Auto Save mode** aktivieren (optional, spart Ctrl+S)
5. **Predefined classes** laden: `classes.txt` (im Regression-Set-Root)

> **Klassen:** `classes.txt` enthält nur die **aktiven** Klassen aus `ml/configs/th_classes.yaml` (12 Stück). Keine Hero-Pads (`kingpad`, `queenpad`, `rcpad`, `wardenpad`).

## Boxen zeichnen

1. Rechteck um Gebäude ziehen
2. Klasse aus der Liste wählen
3. Speichern: **Ctrl+S** (oder Auto Save)
4. Nächstes Bild: **D** (vor) / **A** (zurück)

Pro Bild entsteht eine `.txt`-Datei gleichen Namens im Save-Verzeichnis, z. B.:

```
labels/th15/war_base_illyrian_god.txt
```

Format pro Zeile (YOLO normalisiert):

```
<class_index> <cx> <cy> <width> <height>
```

Beispiel (synthetisch):

```
3 0.322123 0.386599 0.034815 0.047809
8 0.409941 0.742560 0.026453 0.043646
```

## Welche Bilder labeln?

**4 Kern-War-Bases** (Priorität):

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
