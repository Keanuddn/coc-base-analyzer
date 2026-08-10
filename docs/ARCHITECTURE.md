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
| Regression-Set | 2/8 Zielbilder (TH15 vollständig; TH16–TH18 ausstehend) — siehe Inventar unten |
| Inferenz | 32–33 Detections pro Bild, Confidence 0.25–0.90 |
| Annotierte Outputs | `ml/notebooks/phase0_output/*_annotated.jpg` |
| CSV | `ml/notebooks/phase0_results.csv` mit manueller Evaluation |

### TH15-Evaluationsergebnisse (2 Bilder)

| Bild | Detections | Klassen | Correct | FP | FN | Fazit |
|------|------------|---------|---------|----|----|-------|
| `war_base_illyrian_god.png` | 33 | canon (16), mortar (12), inferno (2), airsweeper (1), ad (1), wizztower (1) | ~18 | ~10 | ~22 | Starke Erkennung von Kanonen/Mörsern; schwach bei Eagle, X-Bow, Scattershot, TH15-Neubauten |
| `progress_base_drachen_meddler.png` | 32 | canon (11), wizztower (6), ad (5), mortar (5), bombtower (2), xbow (2), eagle (1) | ~20 | ~8 | ~18 | Gruppierte Verteidigungen gut erkannt; Inferno, Scattershot, Monolith, Spell Tower fehlen |

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
| Regression-Set TH15–TH18 (2 je Level) | ⚠️ 2/8 — TH15 ✅, TH16–TH18 ❌ |
| TH15-Neubauten abgedeckt | ❌ |

**Empfehlung:** Phase 0 ist **teilweise abgeschlossen** — genug für Go zu Phase 1 (Datensatz-Aufbau + Fine-Tuning), aber Regression-Set sollte auf 20–30 Bilder erweitert werden.

### Offene Punkte

1. **Regression-Set vervollständigen:** TH16–TH18 je 2 War-Base-Screenshots nachreichen (TH15 ✅); langfristig auf 20–30 Bilder (`ml/tests/regression_set/th{10-18}/`), inkl. TH13-Basen als Baseline-Vergleich
2. **Neue Klassen** für Phase 1: `monolith`, `spelltower`, `th14`–`th18`, ggf. `archertower`
3. **OpenCV 5.0-Kompatibilität** in Visualisierung (PIL-Fallback oder Pin auf OpenCV 4.x)

### Artefakte

| Datei | Zweck |
|-------|-------|
| `ml/notebooks/phase0_feasibility_check.ipynb` | Interaktiver Machbarkeits-Check |
| `ml/scripts/phase0_smoke_test.py` | Headless Smoke Test |
| `ml/notebooks/phase0_results.csv` | Strukturierte Ergebnisse (2 TH15-Bilder evaluiert) |
| `ml/notebooks/phase0_output/` | Annotierte Bounding-Box-Bilder |
| `ml/tests/regression_set/` | Regression-Set-Inventar (README) |
| `ml/tests/regression_set/th15/` | 2 TH15-Screenshots (War + Progress Base) ✅ |
| `ml/tests/regression_set/th16/` | 0/2 — README mit fehlenden Slots |
| `ml/tests/regression_set/th17/` | 0/2 — README mit fehlenden Slots |
| `ml/tests/regression_set/th18/` | 0/2 — README mit fehlenden Slots |

### Regression-Set-Inventar (TH15–TH18, Stand 2026-08-10)

Nutzer-Ziel: je 2 Screenshots pro Rathaus-Level 15–18 (8 Bilder gesamt).

| TH | Anzahl | Dateien | Klassifikation | Status |
|----|--------|---------|----------------|--------|
| TH15 | 2/2 | `war_base_illyrian_god.png`, `progress_base_drachen_meddler.png` | Beide TH15 (purple/gold Magic-Theme, Monolith, Spell Towers) | ✅ |
| TH16 | 0/2 | — | — | ❌ fehlt |
| TH17 | 0/2 | — | — | ❌ fehlt |
| TH18 | 0/2 | — | — | ❌ fehlt |

**Asset-Eingang 2026-08-10:** 8 neue Screenshots angekündigt; im Workspace nur 2 Dateien gefunden (byte-identische Duplikate der bestehenden TH15-Bilder). TH16–TH18 müssen nachgereicht werden.

**Smoke Test (2026-08-10):** 2 Bilder getestet — je 32–33 Detections, Modell lädt erfolgreich.

### Empfehlung für Phase 1

- Modell als **Baseline für TH13-Basen** nutzbar (mAP 0.874 auf TH13-Daten)
- Für TH14+ ist **Fine-Tuning mit eigenem Datensatz** erforderlich — **durch TH15-Test bestätigt**
- Neue Klassen für TH14–18-Gebäude müssen zum Label-Set hinzugefügt werden
- Regression Set (20–30 Bilder) als kontinuierlicher Qualitäts-Check beibehalten
