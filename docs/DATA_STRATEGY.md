# Datenstrategie

> Phase 1a/1b/1c abgeschlossen. Phase 1d (Dataset Assembly) implementiert.

## Übersicht Phase 1

| Sub-Phase | Ziel | Status |
|-----------|------|--------|
| **1a** | Base-Links harvesten (YouTube, Community-Sites) | ✅ Scaffold |
| **1b** | `link.clashofclans.com` dekodieren | ✅ Structural |
| **1c** | Basis rendern (ClashKing-Sprites + Domain Randomization) | ✅ Prototype |
| **1d** | Datensatz assemblieren (YOLO + Reports) | ✅ Implementiert |

## Link Harvesting (1a)

### Quellen

1. **YouTube** — Suche via Data API v3 (`YOUTUBE_API_KEY`), Regex auf Video-Beschreibungen
2. **Community-Sites** — z. B. clashofclanslayouts.org, weitere Layout-Portale

### Registry-Format (JSONL)

Inspiriert vom JSONL-Pattern aus Community-Projekten wie [nschmeller/clash-bases](https://github.com/nschmeller/clash-bases):

```json
{
  "url": "https://link.clashofclans.com/en?clan=<REDACTED>&tag=<REDACTED>&token=<REDACTED>",
  "source": "youtube",
  "discovered_at": "2026-08-10T15:00:00Z",
  "channel": "Example CoC Channel",
  "video_id": "dQw4w9WgXcQ",
  "page_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "title": "TH18 War Base Anti 3 Star",
  "preview_image_url": null,
  "extra": {}
}
```

Felder:

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `url` | string | Share-Link (dedupliziert) |
| `source` | string | `youtube` oder Hostname |
| `discovered_at` | ISO-8601 UTC (`…Z`) | Harvest-Zeitpunkt |
| `channel` | string? | YouTube-Kanal |
| `site` | string? | Quell-Website |
| `video_id` | string? | YouTube Video-ID |
| `page_url` | string? | Seite, auf der der Link gefunden wurde |
| `preview_image_url` | string? | Layout-Vorschaubild (Sites) |
| `title` | string? | Video-Titel |
| `extra` | object | Erweiterbare Metadaten |

## robots.txt-Policy

Vor dem Crawlen jeder neuen Domain:

1. `robots.txt` per `urllib.robotparser` abrufen und parsen
2. User-Agent: `CoCBaseAnalyzer/0.1` (konfigurierbar via `HARVESTER_USER_AGENT`)
3. **Disallow → Domain in `blocked_domains.yaml` eintragen und überspringen**
4. Kein erneuter Crawl-Versuch für blockierte Domains

### blocked_domains.yaml

```yaml
domains:
  - domain: example.com
    reason: robots.txt disallows /layouts/ for 'CoCBaseAnalyzer/0.1'
    blocked_at: "2026-08-10T15:00:00Z"
    user_agent: CoCBaseAnalyzer/0.1
```

## Rate Limiting

| Mechanismus | Wert |
|-------------|------|
| Max. parallele Requests pro Host | 3 |
| Mindest-Abstand zwischen Requests | 1 s (`HARVESTER_REQUEST_DELAY_SEC`) |
| Backoff bei HTTP 429/503 | Exponentiell, max. 60 s |
| YouTube API | 1 s Pause zwischen Video-Fetches |

## Link Decoding (1b)

Share-Links (`action=OpenLayout`) enthalten **keine Gebäude-Koordinaten** — nur einen
24-Byte-opaque Identifier, den Supercell serverseitig auflöst. Reverse-Engineering
quelle: [nschmeller/clash-bases](https://github.com/nschmeller/clash-bases)
(`scripts/validate-bases.py`, 5 617+ verifizierte Links).

### URL-Format

```
https://link.clashofclans.com/{lang}?action=OpenLayout&id=TH{N}%3A{HV|WB}%3A{blob32}
```

| Segment | Bedeutung |
|---------|-----------|
| `TH{N}` | Town-Hall-Level (1–18+) |
| `HV` | Home Village |
| `WB` | War Base |
| `blob32` | 32 Zeichen Base64url → **24 Bytes** |

### Payload-Struktur (24 Bytes, big-endian)

| Offset | Größe | Feld |
|--------|-------|------|
| 0–3 | 4 B | Collection index (beobachtet: 0–93) |
| 4–7 | 4 B | Layout slot: 1, 2 oder 3 (Layout 1/2/War) |
| 8–23 | 16 B | HMAC-Tag (Supercell-signiert, nicht öffentlich verifizierbar) |

**Wichtig:** Weder `link.clashofclans.com` noch `api.clashofclans.com` liefern
Gebäude-JSON für einen Link. Die Share-Landingpage ist für alle IDs identisch;
nur der In-Game-Deep-Link-Handler löst Layouts auf.

### Ziel-Schema (`DecodedBase`)

```python
BuildingPlacement(building_type, level, x, y, rotation)  # Phase 1c — nicht aus URL
TrapPlacement(trap_type, level, x, y)                      # Phase 1c — nicht aus URL
DecodedBase(
    link, town_hall_level, village_type, layout_slot,
    collection_index, layout_fingerprint, buildings, traps, raw_payload
)
```

`buildings` / `traps` bleiben leer bis Phase 1c (Rendering) oder manueller
Import. Der Decoder liefert strukturelle Metadaten + `layout_fingerprint` für
Content-Dedup.

### Implementierung

| Modul | Zweck |
|-------|-------|
| `link_decoder/format.py` | URL-Parsing, Base64url-Dekodierung, Payload-Extraktion |
| `link_decoder/decoder.py` | `decode_base_link()`, Batch-Decode, Fehler-Logging |
| `link_decoder/dedup.py` | Content-Fingerprint (`TH{N}:{HV\|WB}:{hmac_hex}`) |
| `link_decoder/schema.py` | `DecodedBase`, `BuildingPlacement`, `TrapPlacement` |

Abgelehnte Formate (mit geloggtem Grund, kein Crash):

- `action=CopyArmy` — Truppen-Link, kein Layout
- Legacy `?clan=&tag=&token=` — kein öffentlicher Decoder
- Ungültige Base64url / falsche Payload-Länge / Slot ∉ {1,2,3}

### Content-Dedup (1a-Ergänzung)

Registry dedupliziert URLs (`BaseRegistry._seen_urls`). `dedup.py` vergleicht
dekodierte Identität — gleiche Layout-ID unter `/en?` vs `/de?` oder mit
`&ref=` wird erkannt.

### Test-Vektoren

Verifizierte Links aus Supercell-Blog (MCES TH12, 2019) und
MonsieurSingh/ClashofClans_auto_loot (TH15/TH16). Siehe
`data-pipeline/tests/test_decoder.py`.

### Offen / User-Input für volle Geometrie

Für `building_type, level, x, y, rotation, traps` aus Links:

1. **Nicht möglich** ohne Supercell-HMAC-Key oder In-Game-Capture
2. **Alternative:** Preview-Bilder parsen oder Community-Layout-Dateien importieren (siehe Phase 1c)
3. **Optional:** Nutzer liefert 1–2 Links + In-Game-Screenshot-Paar zur Validierung

## Synthetic Rendering (1c)

OpenLayout-Links liefern **keine Gebäude-Koordinaten**. Phase 1c rendert stattdessen
synthetische Trainingsbilder aus expliziten `BuildingPlacement`-Listen — perfekte YOLO-Labels
aus den Compositing-Koordinaten (Sim-to-Real für Fine-Tuning).

### Sprite-Quelle

| Item | Pfad / Quelle |
|------|----------------|
| Atlas | [ClashKingAssets](https://github.com/ClashKingInc/ClashKingAssets) → `clashking/home-village/` |
| Download | `data-pipeline/src/renderer/sprites/download_clashking_sprites.sh` (472 WebP, gitignored) |
| Mapping | `building_type_map.yaml` — ML-Aliase (`canon`, `ad`, …) → ClashKing-Slugs |
| Lizenz | Supercell IP; Nutzer-Verantwortung — siehe `docs/SPRITE_SOURCES.md` |

Pfad-Template: `clashking/home-village/{slug}/level_{level}.webp`

### Render-Pipeline

```
BuildingPlacement[]  →  IsometricRenderer  →  PNG + YOLO .txt (sidecar)
                              ↑
                    DomainRandomization (Helligkeit, Kontrast, Position, Hintergrund)
```

| Modul | Zweck |
|-------|-------|
| `renderer/isometric_renderer.py` | PIL-Compositing auf 44×44-Kachelgitter; Gebäude über Village-Gras |
| `renderer/village_background.py` | Prozedurales CoC-Gras (Checkerboard, Grid, Waldrand) — keine ClashKing-Scenery |
| `renderer/domain_randomization.py` | Lighting/Position plus Gras-Hue/Helligkeit und Lighting-Overlay |
| `renderer/demo_render.py` | CLI-Demo mit hardcodierten Test-Placements (ohne dekodierte Links) |

**Demo ausführen:**

```bash
cd data-pipeline
python -m renderer.demo_render
# → datasets/processed/demo/sample_base.png + sample_base.txt
```

Fehlende Sprites: Warning + Magenta-Placeholder (Demo) bzw. Skip (Tests ohne Placeholder).

### Sim-to-Real-Strategie

1. **Synthetisch (1c):** ClashKing-Isometric-Sprites + Domain Randomization → großer,
   perfekt gelabelter Trainingspool für TH13–18-Verteidigungen (Monolith, Spell Tower, …).
2. **Real (Regression):** Echte Scouting-Screenshots in `ml/tests/regression_set/` als
   Validierung und Misch-Training.
3. **Domain Gap:** Synthetische Editor-Sprites ≠ In-Game-Scouting (Zoom, UI, Schatten, Scenery).
   Der Renderer legt die ClashKing-Gebäude auf ein **prozedurales Village-Gras** (44×44-Diamant,
   Checkerboard, leichte Grid-Linien, dunkler Waldrand mit einfachen Ellipsen-Bäumen) — nicht
   mehr auf eine flache Grünfläche. ClashKing liefert nur Gebäude-WebP, keine Gras-/Scenery-Tiles;
   Screenshot-Plates wurden nicht committed (große Binaries, Gebäude verdecken das Gras).
   Domain Randomization jittert Gras-Helligkeit/Hue plus ein leichtes Lighting-Overlay.
   **YOLO-Labels bleiben nur Gebäude-Boxen** — Hintergrund wird nicht gelabelt.
   Bulk-Set neu bauen (gitignored unter `datasets/processed/synthetic_v1/`):

   ```bash
   cd data-pipeline
   python -m dataset.generate_synthetic --count 200 --force
   ```

   Legacy-Solid-Grün: `--flat-background`. Bestehende 200 Bilder ohne `--force` bleiben alt.
4. **YOLO-Gap:** Keremberke-Modell kennt nur `th13`, nicht TH14–18 / Monolith / Spell Tower —
   neue Klassen beim Fine-Tuning ergänzen; Sprites sind bereits vorhanden.

### Geometrie-Quellen für volle synthetische Datensätze (Future Work)

Ein **vollständiger synthetischer Datensatz** aus geharvesteten Links braucht Layout-Geometrie
aus einer dieser Quellen (keine ist in 1b aus Links dekodierbar):

| Quelle | Beschreibung | Status |
|--------|--------------|--------|
| Preview-Image-Parsing | `preview_image_url` aus Harvester → Gebäude-Positionen extrahieren | 🔲 Geplant |
| Community-Layout-Dateien | `.json` / `.csv` von Layout-Portalen (nschmeller/clash-bases-Katalog) | 🔲 Optional |
| Manueller Import | `BuildingPlacement`-Listen pro Base | 🔲 Dev/Test |
| In-Game-Capture | Screenshot + manuelles Labeling | 🔲 Validierung |

Bis Geometrie verfügbar ist, liefert `demo_render.py` und manuelle Placements den Render-Pfad.

### Nächste Schritte

1. **Manuelles Labeling:** YOLO-`.txt`-Sidecars für `ml/tests/regression_set/` anlegen
2. **Preview-Parsing:** Layout-Geometrie aus Harvester-Vorschaubildern (oder Community-Files)
3. Harvester-Lauf → Batch-Decode → Supabase-Persist (`decode_status`)
4. **Phase 2:** Fine-Tuning v2 (2026-08-17) auf `yolo_v1` (209 synthetic + 4 manual). Synthetic val looks strong; real-screenshot recall remains too low for use. More real labels (or domain-randomized renders closer to scouting UI) needed before another train.

## Dataset Assembly (1d)

Kombiniert synthetische Renders (Phase 1c) und echte Regression-Screenshots zu einem
Ultralytics-kompatiblen YOLO-Dataset mit Train/Val/Test-Split, TH-Balance-Report und
Real-vs-Synthetic-Ratio.

### Module

| Modul | Zweck |
|-------|-------|
| `dataset/dedup.py` | Content-Dedup für Registry-Einträge (`layout_content_key`) + SHA-256-Bild-Dedup |
| `dataset/build_dataset.py` | YOLO-Assembly, Split, `data.yaml`, `dataset_report.json` |

Registry-URL-Dedup (1a) bleibt in `BaseRegistry`; `dataset/dedup.py` ergänzt
**dekodierte Layout-Identität** — gleiche Base unter `/en?` vs `/de?` wird erkannt.
Low-Level-Fingerprint: `link_decoder/dedup.py` (`layout_content_key`).

### CLI

```bash
cd data-pipeline
python -m dataset.build_dataset \
  --output datasets/processed/yolo_v1 \
  --include-demo \
  --include-regression
```

Optionen: `--train-ratio`, `--val-ratio`, `--test-ratio`, `--seed`, `--user-screenshots`,
`--synthetic-variants` (Extra-Renders wenn Sprites vorhanden), `--no-render-variants`.

### Output-Layout

```
datasets/processed/yolo_v1/
├── data.yaml
├── dataset_report.json
├── dataset_report.md
├── train/images/ + train/labels/
├── val/images/ + val/labels/ + val/images_unlabeled/
└── test/images/ + test/labels/ + test/images_unlabeled/
```

### Real vs Synthetic

| Quelle | Labels | Split |
|--------|--------|-------|
| Demo + synthetische Varianten | ✅ perfekt (Renderer) | train/val/test |
| `ml/tests/regression_set/` | ❌ fehlen initial | `images_unlabeled/` in val/test |

`dataset_report.json` enthält Pflicht-Counter: `totals`, `real_vs_synthetic_ratio`,
`town_hall_balance`, `unlabeled_real_images.warning`.

**Labeling-TODO:** Echte Screenshots manuell labeln oder Pseudo-Labels mit
`keremberke/yolov5m-clash-of-clans` erzeugen (manuell prüfen — im Report vermerkt).
Deprecated Helden-Pads (`kingpad`, `queenpad`, `rcpad`, `wardenpad`) werden beim
Pseudo-Labeling standardmäßig herausgefiltert (`ml/src/pseudo_label.py`, conf=0.35).

### Empfehlung bei kleinem Datensatz

Mit wenigen echten Screenshots (<20 manuell geprüfte Labels) zuerst **nur synthetisch
trainieren** (ClashKing-Renderer + Domain Randomization). Echte TH15/16-Screenshots
liefern ohne manuelles Labeling oder deutlich besseres Modell vor allem Rauschen —
Pseudo-Labels vom keremberke-Baseline sind auf TH14+ unzuverlässig (fehlende Klassen,
veraltete Helden-Pads). Erst nach Review freigegebene Regression-Labels in den Mix
nehmen; alternativ bewusst synthetic-only bis mehr manuelle Labels vorliegen.

TH wird aus Ordner (`th15/`) oder Dateiname (`th13_war_…`) inferiert; `_extras/`-Bilder
fließen mit ein, können `unknown` TH haben.

## Supabase (Future)

Stub in `db/supabase_client.py`. Geplante Tabelle `base_links`:

- Spiegelung der JSONL-Felder + `decode_status` (`pending` | `success` | `failed`)
- Env: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`

## Regression Set (Phase 0)

Für den Machbarkeits-Check werden 20–30 Screenshots benötigt:

```
ml/tests/regression_set/
├── th10/ … th18/
```

- **Format:** PNG oder JPG
- **Inhalt:** Gegner-Basis-Screenshots (Scouting-Ansicht)
- TH17/TH18-Misclassification im Regression Set — bekannt, Fix später

Details zu Labeling und Augmentation: siehe Abschnitt **Dataset Assembly (1d)** oben.
