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

| Aspekt | Ergebnis |
|--------|----------|
| Modell-Laden | Erfolgreich (HF-Weights) |
| Regression-Set | Leer — keine CoC-Screenshots unter `ml/tests/regression_set/` |
| HF-Beispielbild | Download fehlgeschlagen: Dataset-Skripte von Hugging Face nicht mehr unterstützt |
| Fallback-Inferenz | `yolov5/data/images/zidane.jpg` — **0 Detections**, Klassen `[]` (kein CoC-Inhalt; bestätigt nur Pipeline) |
| CSV | `ml/notebooks/phase0_results.csv` aktualisiert (`smoke_test_only`) |

Für aussagekräftige Detections CoC-Basis-Screenshots ins Regression-Set legen und den Smoke Test erneut ausführen.

### Erwartete Eignung (basierend auf Model Card)

| TH-Level | Erwartung | Begründung |
|----------|-----------|------------|
| TH10–TH12 | Möglicherweise brauchbar | Viele Gebäude (canon, mortar, xbow, inferno) sind im Dataset; TH-spezifische Klasse fehlt |
| TH13 | **Am besten geeignet** | Einzige explizite TH-Klasse (`th13`); Scattershot, Giga-Inferno-Pads enthalten |
| TH14–TH15 | Eingeschränkt | Neue Gebäude (Monolith ab TH14, Spell Tower ab TH15) nicht im Training |
| TH16–TH18 | **Voraussichtlich unzureichend** | Training-Daten von 2022; TH16+ existierte nicht. Keine Klassen für neue Verteidigungen (Giga Inferno TH16+, neue Truppen-Pads, etc.) |

### Offene Punkte (Nutzer-Aktion erforderlich)

1. **20–30 Screenshots bereitstellen** unter:
   ```
   ml/tests/regression_set/th{10-18}/*.png
   ```
   Gegner-Basis-Screenshots (Scouting-Ansicht), verschiedene TH-Levels.

2. **Smoke Test erneut ausführen**, sobald Regression-Set-Bilder vorliegen:
   ```bash
   ml/.venv/bin/python ml/scripts/phase0_smoke_test.py
   ```
   (Initialer Lauf ohne CoC-Bilder: Modell OK, 0 Detections auf YOLOv5-Fallback.)

3. **Manuelle Evaluation** im Notebook: pro Bild `correct`, `false_positives`, `false_negatives` eintragen.

### Artefakte

| Datei | Zweck |
|-------|-------|
| `ml/notebooks/phase0_feasibility_check.ipynb` | Interaktiver Machbarkeits-Check |
| `ml/scripts/phase0_smoke_test.py` | Headless Smoke Test |
| `ml/notebooks/phase0_results.csv` | Strukturierte Ergebnisse (Smoke Test 2026-08-09: Fallback-Bild, 0 Detections) |
| `ml/tests/regression_set/th{10-18}/` | Regression-Set-Ordner (leer, bereit für Screenshots) |

### Empfehlung für Phase 1

- Modell als **Baseline für TH13-Basen** nutzbar (mAP 0.874 auf TH13-Daten)
- Für TH14+ ist **Fine-Tuning mit eigenem Datensatz** erforderlich
- Neue Klassen für TH14–18-Gebäude müssen zum Label-Set hinzugefügt werden
- Regression Set (20–30 Bilder) als kontinuierlicher Qualitäts-Check beibehalten
