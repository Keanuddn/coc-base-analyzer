# Architektur — CoC Base Analyzer

## Übersicht

Das Projekt ist als **Monorepo** aufgebaut. Die Pipeline verarbeitet Screenshots gegnerischer Clash-of-Clans-Basen und liefert strukturierte Analyseergebnisse.

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│  Frontend   │────▶│   Backend    │────▶│  ML / Inferenz  │
│  (Upload)   │     │  (API/Orche.)│     │  (YOLOv5 CV)    │
└─────────────┘     └──────┬───────┘     └────────┬────────┘
                           │                       │
                           ▼                       ▼
                    ┌──────────────┐     ┌─────────────────┐
                    │ Knowledge    │     │  data-pipeline  │
                    │ Base         │     │  (Labeling)     │
                    └──────────────┘     └─────────────────┘
```

| Paket | Zweck | Phase |
|-------|-------|-------|
| `ml/` | Modell-Inferenz, Training, Evaluation | 0+ |
| `data-pipeline/` | Datensatz-Ingestion, Labeling | 1+ |
| `knowledge-base/` | Kuratierte Spielregeln, Truppen, Meta | 2+ |
| `backend/` | REST/gRPC API, Orchestrierung | 3+ |
| `frontend/` | Upload-UI, Ergebnis-Darstellung | 4+ |
| `docs/` | Spezifikation, ADRs, Architektur | 0+ |

### Datenfluss (Zielbild)

1. **Input:** Screenshot der gegnerischen Basis (Scouting-Ansicht)
2. **CV-Inferenz:** YOLO-Modell erkennt Gebäude und Verteidigungen (Bounding Boxes + Klassen)
3. **Post-Processing:** Normalisierung der Detektionen, TH-Level-Schätzung, Basistyp-Klassifikation
4. **Knowledge Base:** Angriffsplan-Vorschläge basierend auf erkannten Strukturen und kuratierten Regeln
5. **Output:** JSON mit Detektionen, Basistyp, Fallen-Wahrscheinlichkeiten, Angriffsplan

---

## Phase 0: Machbarkeits-Check

### Ziel

Prüfen, ob das öffentliche Modell `keremberke/yolov5m-clash-of-clans` als Startpunkt für die CV-Pipeline nutzbar ist.

### Modell-Informationen (Model Card)

Quelle: [keremberke/yolov5m-clash-of-clans](https://huggingface.co/keremberke/yolov5m-clash-of-clans)

| Eigenschaft | Wert |
|-------------|------|
| Architektur | YOLOv5m |
| Framework | `yolov5` Python-Paket |
| Trainings-Dataset | [keremberke/clash-of-clans-object-detection](https://huggingface.co/datasets/keremberke/clash-of-clans-object-detection) |
| Dataset-Größe | 125 Bilder (88 train / 24 valid / 13 test) |
| Dataset-Export | 30. März 2022 (Roboflow) |
| Modell-Update | 30. Dezember 2022 |
| mAP@0.5 | **0.874** |
| Lizenz | CC BY 4.0 |

#### Erkannte Klassen (16)

```
ad, airsweeper, bombtower, canon, clancastle, eagle, inferno,
kingpad, mortar, queenpad, rcpad, scattershot, th13, wardenpad,
wizztower, xbow
```

**Wichtig:** Das einzige explizite Rathaus-Level in den Labels ist `th13`. Es gibt keine Klassen für TH14–TH18 oder deren exklusive Gebäude (Monolith, Spell Tower, Giga Inferno Level 6+, etc.).

### Smoke-Test-Ergebnis

| Check | Status | Details |
|-------|--------|---------|
| Python venv (`ml/.venv`) | ✅ | Python 3.14.3, alle Dependencies installiert |
| `yolov5` Import | ✅ | Paket importierbar |
| Modell-Download von HF | ❌ | `huggingface.co` nicht erreichbar (DNS/Netzwerk-Fehler) |
| Inferenz auf Testbildern | ⏸️ | Blockiert — Modell konnte nicht geladen werden |
| Lokale CoC-Screenshots | ❌ | Keine gefunden in Projekt, Downloads oder Pictures |

**Fehlermeldung (Smoke Test):**
```
Model load FAILED: MaxRetryError — Failed to resolve 'huggingface.co'
```

**Nächster Schritt für den Nutzer:** Smoke Test lokal mit Netzwerk ausführen:
```bash
cd coc-base-analyzer
ml/.venv/bin/python ml/scripts/phase0_smoke_test.py
```

---

## Phase 0 Ergebnisse

### Zusammenfassung

Phase 0-Infrastruktur ist vollständig eingerichtet (Notebook, Smoke-Test-Skript, Regression-Set-Struktur, CSV-Export). Der Smoke Test wurde **lokal mit Netzwerk erfolgreich ausgeführt** (2026-08-09 UTC): Modell `keremberke/yolov5m-clash-of-clans` lädt und Inference läuft (PyTorch 2.6+ erfordert `weights_only=False` beim Laden des YOLOv5-Checkpoints — im Skript abgedeckt).

**Erste Evaluation auf echten TH15-Screenshots** (2026-08-10 UTC): 2 Bilder im Regression-Set getestet. Das Modell erkennt grundlegende Verteidigungen, ist aber für TH15 unvollständig.

| Aspekt | Ergebnis |
|--------|----------|
| Modell-Laden | Erfolgreich (HF-Weights) |
| Regression-Set | 4/8 Zielbilder (TH15+TH16 ✅; TH17–TH18 ausstehend) — siehe Inventar |
| Inferenz | 27–53 Detections pro Bild (TH13 am besten), Confidence 0.25–0.93 |
| Annotierte Outputs | `ml/notebooks/phase0_output/*_annotated.jpg` |
| CSV | `ml/notebooks/phase0_results.csv` (6 Bilder, Smoke Test 2026-08-10) |

### Smoke-Test-Ergebnisse (6 Bilder, 2026-08-10)

| Bild | Detections | Klassen | Correct | FP | FN | Fazit |
|------|------------|---------|---------|----|----|-------|
| `th15/war_base_001.png` (ILLYRIAN GOD) | 33 | canon (16), mortar (12), inferno (2), airsweeper (1), ad (1), wizztower (1) | ~18 | ~10 | ~22 | Starke Erkennung von Kanonen/Mörsern; schwach bei Eagle, X-Bow, Scattershot, TH15-Neubauten |
| `th15/war_base_002.png` (CocBase) | 52 | canon (11), wizztower (6), ad (5), mortar (5), bombtower (2), xbow (2), eagle (1) | ~20 | ~8 | ~18 | Gruppierte Verteidigungen gut erkannt; Inferno, Scattershot, Monolith, Spell Tower fehlen |

**Erkannte Klassen (beide Bilder):** `ad`, `airsweeper`, `bombtower`, `canon`, `eagle`, `inferno`, `mortar`, `wizztower`, `xbow`

**Nicht erkannt (TH15-spezifisch oder fehlend im Label-Set):** Town Hall (`th13`-Klasse passt visuell nicht), Monolith, Spell Tower, Scattershot (war base), Clan Castle, Hero-Pads, Ressourcen-Gebäude

**Visuelle Beobachtungen:**
- TH15-Gebäude-Skins (lila/gold statt TH13-Eis-Theme) reduzieren Erkennungsrate nicht vollständig — Silhouetten von Kanonen, Mörsern, Infernos bleiben brauchbar
- Progress-Base-Layout (Gebäude gruppiert) liefert bessere Detections als War-Base (dichte, überlappende Verteidigungen)
- Viele Low-Confidence-Boxen (0.25–0.35) deuten auf unsichere Klassifikation hin
- `yolov5.render()` schlägt mit OpenCV 5.0 fehl (readonly-Array); Annotation via PIL-Workaround

### Erwartete Eignung (basierend auf Model Card + TH15-Test)

| TH-Level | Erwartung | Begründung |
|----------|-----------|------------|
| TH10–TH12 | Möglicherweise brauchbar | Viele Gebäude (canon, mortar, xbow, inferno) sind im Dataset; TH-spezifische Klasse fehlt |
| TH13 | **Am besten geeignet** | Einzige explizite TH-Klasse (`th13`); Scattershot, Giga-Inferno-Pads enthalten |
| TH14–TH15 | Eingeschränkt | Neue Gebäude (Monolith ab TH14, Spell Tower ab TH15) nicht im Training — **bestätigt durch Test** |
| TH16–TH18 | **Voraussichtlich unzureichend** | Training-Daten von 2022; TH16+ existierte nicht. Keine Klassen für neue Verteidigungen (Giga Inferno TH16+, neue Truppen-Pads, etc.) |

### Phase-0-Go/No-Go

| Kriterium | Status |
|-----------|--------|
| Pipeline funktioniert (Modell laden, Inferenz, CSV) | ✅ |
| Detections auf echten CoC-Screenshots | ✅ (32–33 pro Bild) |
| Brauchbare Baseline für TH15 | ⚠️ Teilweise — nur Grundverteidigungen |
| Regression-Set TH15–TH18 (2 je Level) | ⚠️ 4/8 — TH15+TH16 ✅, TH17–TH18 ❌ |
| TH15-Neubauten abgedeckt | ❌ |

**Empfehlung:** Phase 0 ist **teilweise abgeschlossen** — genug für Go zu Phase 1 (Datensatz-Aufbau + Fine-Tuning), aber Regression-Set sollte auf 20–30 Bilder erweitert werden.

### Offene Punkte

1. **Regression-Set vervollständigen:** TH17–TH18 je 2 War-Base-Screenshots nachreichen (TH15+TH16 ✅); langfristig auf 20–30 Bilder (`ml/tests/regression_set/th{10-18}/`), inkl. TH13-Basen als Baseline-Vergleich
2. **Neue Klassen** für Phase 1: `monolith`, `spelltower`, `th14`–`th18`, ggf. `archertower`
3. **OpenCV 5.0-Kompatibilität** in Visualisierung (PIL-Fallback oder Pin auf OpenCV 4.x)

### Artefakte

| Datei | Zweck |
|-------|-------|
| `ml/notebooks/phase0_feasibility_check.ipynb` | Interaktiver Machbarkeits-Check |
| `ml/scripts/phase0_smoke_test.py` | Headless Smoke Test |
| `ml/notebooks/phase0_results.csv` | Strukturierte Ergebnisse (4 Kernbilder: TH15×2, TH16×2; Extras optional) |
| `ml/notebooks/phase0_output/` | Annotierte Bounding-Box-Bilder |
| `ml/tests/regression_set/` | Regression-Set-Inventar (README) |
| `ml/tests/regression_set/th13/` | leer (keine verifizierten TH13-Screenshots) |
| `ml/tests/regression_set/th15/` | 2 TH15 War Bases ✅ |
| `ml/tests/regression_set/_extras/` | Reserve-Layouts (Progress Base + CocBase-Extras) |
| `ml/tests/regression_set/th16/` | 2 TH16 War Bases ✅ |
| `ml/tests/regression_set/th17/` | 2 Screenshots, 0 Gold |
| `ml/tests/regression_set/th18/` | 3 Screenshots, 1 reviewed Gold (`th18_lukas`, 85 Boxen) |

### Regression-Set-Inventar (TH15–TH18, Stand 2026-08-10)

Nutzer-Ziel: je 2 Screenshots pro Rathaus-Level 15–18 (8 Bilder gesamt).

| TH | Anzahl | Dateien | Klassifikation | Status |
|----|--------|---------|----------------|--------|
| TH13 | 2/2 | `war_base_001.png`, `war_base_002.png` | TH13 (blue/ice theme) — Bonus-Baseline | ✅ |
| TH15 | 2/2 | `war_base_001.png` (in-game), `war_base_002.png` (CocBase) | TH15 purple/gold Magic-Theme | ✅ |
| TH16 | 2/2 | `war_base_001.png`, `war_base_002.png` | TH16 red/gold theme | ✅ |
| TH17 | 2 Screenshots | `th17_img_7306.png`, `th17_img_7307.png` | unlabeled | ❌ kein Gold |
| TH18 | 3 Screenshots / 1 Gold | `th18_lukas.png` (+ aggressor, vinsmoke unlabeled) | reviewed, 85 Boxen | ✅ |

**Asset-Eingang 2026-08-10:** 8 Nutzer-Screenshots aus Cursor workspaceStorage importiert. 3× TH15, 2× TH16, 3× TH13 (falsch gelabelt). TH17/TH18 nicht enthalten.

**Smoke Test (2026-08-10):** 6 Bilder getestet — TH13: 38–53 Det., TH15: 33–52 Det., TH16: 27–33 Det.

### Empfehlung für Phase 1

- Modell als **Baseline für TH13-Basen** nutzbar (mAP 0.874 auf TH13-Daten)
- Für TH14+ ist **Fine-Tuning mit eigenem Datensatz** erforderlich — **durch TH15-Test bestätigt**
- Neue Klassen für TH14–18-Gebäude müssen zum Label-Set hinzugefügt werden
- Regression Set (20–30 Bilder) als kontinuierlicher Qualitäts-Check beibehalten

---

## Phase 2: Pseudo-Labels, Fine-Tuning, Inferenz

### Ziel

Erweiterung der CV-Pipeline um Pseudo-Labeling, YOLO-Fine-Tuning (Ultralytics YOLOv8), Single-Image-Inferenz und Regression-Checks gegen die keremberke-Baseline.

### Komponenten

| Datei | Zweck |
|-------|-------|
| `ml/src/pseudo_label.py` | Keremberke-Modell → YOLO `.txt` für Regression-Screenshots |
| `ml/configs/th_classes.yaml` | Versionierte Klassenliste (16 aktiv + TH14+ Platzhalter) |
| `ml/configs/train_config.yaml` | Epochen, Batch, Pfade, Smoke-Test-Overrides |
| `ml/src/train.py` | Ultralytics Fine-Tuning (`yolov8n.pt` → eigenes Dataset) |
| `ml/src/infer.py` | Screenshot → JSON (Gebäude + Confidence) |
| `ml/src/regression_check.py` | Baseline vs. fine-tuned auf Regression-Set |
| `ml/src/base_classifier.py` | Stub: TH-Schätzung aus Gebäudeverteilung |
| `ml/src/trap_heuristics.py` | Stub: Fallen-Wahrscheinlichkeit (Disclaimer) |

### Pseudo-Labels

```bash
cd coc-base-analyzer/ml
.venv/bin/python src/pseudo_label.py
```

- Output: `ml/tests/regression_set/labels/<rel_path>.txt`
- Metadaten: `labels/_pseudo_label_metadata.json` mit `"pseudo_label": true`
- **Manuelle Review erforderlich** — erwartete Fehler: FP auf TH14+, fehlende Monolith/Spell Tower

### Dataset mit Pseudo-Labels

```bash
cd data-pipeline
.venv/bin/python -m dataset.build_dataset \
  --output datasets/processed/yolo_v1 \
  --include-demo --include-regression --include-pseudo-labels
```

### Training

**Smoke Test (CPU, 2 Epochen):**
```bash
cd ml && .venv/bin/python src/train.py --smoke-test
```

**Volles Training (Colab/GPU empfohlen):**
```bash
cd ml && .venv/bin/python src/train.py
```

Weights landen in `ml/runs/coc_yolo_v1/` (gitignored `*.pt`).

### Inferenz

```bash
cd ml
.venv/bin/python src/infer.py tests/regression_set/th15/war_base_illyrian_god.png
.venv/bin/python src/infer.py --baseline tests/regression_set/th15/war_base_illyrian_god.png
```

### Regression Check

```bash
cd ml
.venv/bin/python src/regression_check.py --baseline-only
.venv/bin/python src/regression_check.py
```

Report: `ml/tests/regression_check_report.json`

### PyTorch 2.6+ Workaround

Keremberke YOLOv5-Checkpoints erfordern `weights_only=False` beim `torch.load` — implementiert in `ml/src/model_utils.py`.

### Einschränkungen Phase 2

- Pseudo-Labels sind **Rauschen**, kein Ground Truth
- TH14–18-Klassen sind Platzhalter in `th_classes.yaml`, noch nicht im Modell-Head
- CPU-Training: nur Smoke Test; volles Fine-Tuning auf GPU/Colab **oder Apple MPS**
- **First training pass (2026-08-16):** 4 manuell gelabelte Kern-War-Bases (TH15+TH16 gemischt). Klasse `th13` ist das Rathaus (Legacy-Name aus keremberke) — TH15/TH16-Halls teilen denselben Slot. Labels sind unvollständig (fehlende Gebäude akzeptiert). Siehe `ml/docs/MANUAL_LABELING.md`.
- **v2 training (2026-08-17):** `yolo_v1` = 213 labeled (209 synthetic bulk + 4 manual). YOLOv8n, MPS, 43/50 epochs (disk full during epoch 44; best at epoch 39). Synthetic val: mAP50 **0.988**, mAP50-95 **0.869**. Real screenshots: 10 boxes on TH15 Illyrian God (was 0; GT 31) and 4 on TH16 volcanic (was 0; GT 28). **Not usable on real scouting screenshots** — val is synthetic-only; the 4 real labels sit in train and are drowned by synthetic appearance. Weights stay gitignored (`*.pt`).

