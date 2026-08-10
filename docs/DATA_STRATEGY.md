# Datenstrategie

> Phase 1a — Link Harvesting (aktiv). Rendering (1c) und Dataset Assembly (1d) folgen.

## Übersicht Phase 1

| Sub-Phase | Ziel | Status |
|-----------|------|--------|
| **1a** | Base-Links harvesten (YouTube, Community-Sites) | ✅ Scaffold |
| **1b** | `link.clashofclans.com` dekodieren | 🔲 Stub |
| **1c** | Basis rendern (ohne Supercell-Assets) | 🔲 Geplant |
| **1d** | Datensatz assemblieren + Supabase persistieren | 🔲 Geplant |

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

## Link Decoding (1b) — Roadmap

Share-Links enthalten ein komprimiertes/encodiertes Layout-Payload. Phase 1b reverse-engineert das Format.

### Ziel-Schema (`DecodedBase`)

```python
BuildingPlacement(building_type, level, x, y, rotation)
TrapPlacement(trap_type, level, x, y)
DecodedBase(link, town_hall_level, buildings, traps, raw_payload)
```

### Aktueller Stand

- `link_decoder/decoder.py` — Stub: URL-Validierung, Payload-Extraktion, Fehler-Logging
- Fehlgeschlagene Dekodierungen werden in-memory geloggt (`get_failed_decodings()`)
- **TODO:** Payload-Format analysieren (Community-Tools, clash-bases Referenz)

### Nächste Schritte 1b

1. Sample-Links aus Registry sammeln (TH14–TH18)
2. Payload-Struktur dokumentieren (Base64, Kompression, Building-IDs)
3. Decoder implementieren + Unit-Tests mit bekannten Layouts
4. TH-Level aus Gebäude-Set ableiten

## Supabase (1d)

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

Details zu Labeling, Augmentation und Trainingsdaten folgen in Phase 1c/1d.
