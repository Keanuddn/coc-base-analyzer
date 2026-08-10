# Sprite Sources — Phase 1c Rendering Research

Research date: 2026-08-10. User decision: use real in-game building visuals; licensing
responsibility accepted by project owner.

Goal: find isometric/top-down building sprites suitable for synthetic layout renders that
visually match in-game scouting views (ML training + preview pipeline).

## Project building identifiers (verified)

From `docs/ARCHITECTURE.md` (YOLOv5 label set) and `data-pipeline/src/link_decoder/schema.py`:

| ML / schema `building_type` | Notes |
|----------------------------|-------|
| `ad` | Air Defense |
| `airsweeper` | Air Sweeper |
| `bombtower` | Bomb Tower |
| `canon` | Cannon (historic spelling in label set) |
| `clancastle` | Clan Castle |
| `eagle` | Eagle Artillery |
| `inferno` | Inferno Tower |
| `mortar` | Mortar |
| `scattershot` | Scattershot |
| `wizztower` | Wizard Tower |
| `xbow` | X-Bow |
| `th13` | Only explicit TH class in YOLO; TH14–18 need `town_hall` sprites by level |
| `monolith`, `spelltower` | Required for TH14+ renders; not yet in YOLO labels |

Phase 1c renderer should map these to sprite paths via
`data-pipeline/src/renderer/sprites/building_type_map.yaml`.

---

## Top 3 recommendations (ranked)

### 1. ClashKingAssets / assets.clashk.ing — **recommended primary source**

| Field | Value |
|-------|-------|
| **Name** | [ClashKingInc/ClashKingAssets](https://github.com/ClashKingInc/ClashKingAssets) |
| **CDN** | https://assets.clashk.ing |
| **License** | Repo/tooling: **GPL-3.0**. Asset files: **Supercell IP** (extracted from game `.sc`/`.sctx`). CDN README invites use with attribution; not a Supercell grant. |
| **Coverage** | Home Village buildings through **TH18** (`town_hall/level_1` … `level_18`). Defenses: cannon (21 lv), mortar (18), inferno_tower (12), eagle_artillery (7), x-bow (13), scattershot (7), monolith (5), spell_tower (4), firespitter (3), ricochet_cannon (4), plus air_defense, wizard_tower, bomb_tower, air_sweeper, hidden_tesla, clan_castle, TH17+ towers. **512 WebP** under `assets/buildings/home-village/`. |
| **View / quality** | **Isometric layout renders** extracted from game files. Typical size ~100–220 px, RGBA WebP, transparent background. Visually closest to in-game village editor / scouting view. |
| **ML suitability** | **Excellent** — same asset pipeline used by [ClashKing](https://github.com/ClashKingInc) OSS tools. Matches silhouette and skin progression for TH13–18 themes. |
| **Download** | Sparse git clone or `download_clashking_sprites.sh` (see sprites README). CDN requires browser-like `User-Agent`; bulk `urllib` gets 403. |

**Sample URL pattern:**

```
https://assets.clashk.ing/buildings/home-village/{building_slug}/level_{n}.webp
```

Slug rule (from upstream README): lowercase, spaces → `_`, strip punctuation.

---

### 2. chiefpansancolt/clash-of-clans-data — **secondary: metadata + wiki fallbacks**

| Field | Value |
|-------|-------|
| **Name** | [chiefpansancolt/clash-of-clans-data](https://github.com/chiefpansancolt/clash-of-clans-data) (npm: `clash-of-clans-data`) |
| **License** | **MIT** (package). Images sourced from [Clash of Clans Wiki (Fandom)](https://clashofclans.fandom.com/wiki/). |
| **Coverage** | 22 Home Village defenses with level records; images include normal, depleted, geared-up, mode variants. monolith (4 lv), spell-tower (10 paths), scattershot, inferno modes, etc. Town Hall images under separate paths. |
| **View / quality** | **Mixed.** Small square icons (~200×200) for some defenses; large gallery renders for others (e.g. monolith ~1052×1475). Not consistently isometric layout sprites. |
| **ML suitability** | **Moderate** — good for level/count metadata and variant names; **not** ideal as sole render source (visual domain gap vs in-game). |
| **Legal** | MIT on repo; wiki/Fandom content and Supercell Fan Content Policy still apply to images. |

Use for: building level tables, spell-tower mode names, cross-checking upgrade counts. Prefer ClashKing WebP for actual compositing.

---

### 3. Statscell/clash-assets — **TH icon pack only**

| Field | Value |
|-------|-------|
| **Name** | [Statscell/clash-assets](https://github.com/Statscell/clash-assets) |
| **License** | **MIT** (+ Supercell fan-content disclaimer in README) |
| **Coverage** | ~170 PNGs: `townhalls/1.png`–`17.png` (TH level **icons**), Builder Hall icons, troop icons/models. **No** defense layout sprites. |
| **View / quality** | Flat profile/icon art, not isometric base tiles. |
| **ML suitability** | **Low** for layout rendering; optional UI badges only. |
| **OSS usage** | Used by various community tools for TH badges. |

---

## Other candidates (documented, not primary)

### nschmeller/clash-bases — catalogue, not sprite library

| Field | Value |
|-------|-------|
| **URL** | https://github.com/nschmeller/clash-bases |
| **Visuals** | **Full-base preview JPEGs/PNG** hotlinked from cocbases.com, basemelon.com, blueprintcoc.com — not per-building sprites. |
| **License** | MIT (site code). Preview images: **site/catalogue copyright**; README requires attribution and no bulk re-hosting. |
| **Relevance** | Harvester preview URLs for Phase 1c screenshot fallback; **not** a sprite atlas. Validator requires `image` ≥200×200 per base entry. |

### Tristanox/COC-Sprites / COC-Sprites-buildings

| Field | Value |
|-------|-------|
| **URL** | https://github.com/Tristanox/COC-Sprites-buildings |
| **Status** | **Unavailable** (GitHub API 404 as of 2026-08-10). Previously advertised TH17 building folders (cannon, xbow, scattershot, etc.). |
| **Assessment** | Would have been strong if public; monitor for re-publish. |

### naathael/clashofclans-assets

| Field | Value |
|-------|-------|
| **URL** | https://github.com/naathael/clashofclans-assets |
| **License** | **None**; README cites Supercell Fan Content Policy only. |
| **Coverage** | Versioned dumps (e.g. `2024-11-25/buildings/`) — **~25k numeric PNGs** (`10000_0.png`), plus raw backgrounds/characters. |
| **View** | Raw extracted frames; requires game-data ID → building mapping. |
| **ML suitability** | High fidelity but **high integration cost** vs ClashKing named exports. |

### Enjoyop2/Clash-of-Clans-data-assets

| Field | Value |
|-------|-------|
| **URL** | https://github.com/Enjoyop2/Clash-of-Clans-data-assets |
| **License** | **Not stated** (educational/private-server disclaimer) |
| **Content** | Compressed CSV/level/localization dumps; not a curated sprite pack. |

### dmccrthy/clash-base-builder

| Field | Value |
|-------|-------|
| **URL** | https://github.com/dmccrthy/clash-base-builder |
| **Sprites** | Minimal set: cannon l1–l2, walls, town_halls th1–**th17** (no th18 at time of check). Tiny WebP (~100×82 cannon). |
| **License** | Not declared on repo |
| **Assessment** | Proof-of-concept only; insufficient coverage for TH13–18 defense set. |

### CocBase / cocbases.com / clashofclanslayouts.org

| Field | Value |
|-------|-------|
| **Assets** | Full-layout preview images on catalogue pages. |
| **Legal** | **Site-owned previews**; terms restrict scraping/bulk use. Suitable as harvester `preview_url` targets (already used in regression set), **not** redistributable sprite sheets. |
| **Visual** | Rendered base screenshots — useful as render **validation** targets, not compositing layers. |

### Clash of Clans Wiki (Fandom)

| Field | Value |
|-------|-------|
| **Content** | Gallery PNGs, stats, upgrade tables. |
| **License** | Fandom/CC-BY-SA community content + Supercell IP on art. |
| **Visual** | Mix of icons, 3D marketing angles, and occasional top-down renders — inconsistent for ML domain matching. |

### Game-file extractors (DIY)

| Tool | License | Notes |
|------|---------|-------|
| [ClashKingAssets extractor](https://github.com/ClashKingInc/ClashKingAssets) (Go) | GPL-3.0 | Same output as CDN; for custom exports / newest patch. |
| [Supercell-Extractor](https://github.com/baraklevy20/Supercell-Extractor) | Node | `.sc` → PNG, movie clips optional. |
| [sc-workshop/SC](https://github.com/sc-workshop/SC) | Adobe Animate pipeline; heavy setup. |

---

## Download status (this repo)

| Item | Path | Committed? |
|------|------|------------|
| ClashKing Home Village WebP (472 files, ~4.8 MB) | `data-pipeline/src/renderer/sprites/clashking/home-village/` | **No** — gitignored (Supercell IP) |
| Download script | `data-pipeline/src/renderer/sprites/download_clashking_sprites.sh` | Yes |
| Building type map | `data-pipeline/src/renderer/sprites/building_type_map.yaml` | Yes |
| Attribution README | `data-pipeline/src/renderer/sprites/README.md` | Yes |

Local fetch verified 2026-08-10 via sparse clone of ClashKingInc/ClashKingAssets.

---

## Recommended next step for Phase 1c

1. **Lock ClashKing WebP as render atlas** — use `building_type_map.yaml` to resolve
   `building_type` + `level` → `level_{n}.webp`.
2. **Prototype `isometric_renderer.py`** — PIL compositing on 44×44 (or 48×48) tile grid;
   align sprite footpoint to `(x, y)` from future decoder; default rotation 0.
3. **TH skin selection** — pass `town_hall_level` from decoded link to pick themed defense
   levels (max level capped by TH).
4. **Validate against regression previews** — compare synthetic render to CocBase / in-game
   screenshots in `ml/tests/regression_set/th{15,16}/`.
5. **Optional** — pin `clash-of-clans-data` npm package for level metadata; keep ClashKing
   for pixels only.
6. **YOLO gap** — add `monolith`, `spelltower`, `th14`–`th18` labels when fine-tuning;
   sprites already cover monolith/spell_tower/town_hall 14–18.

---

## Legal note

All real CoC art is **Supercell Oy** intellectual property. Community repos and MIT/GPL
licenses cover **hosting code**, not a transfer of game-asset rights. This project uses assets
under the owner's acceptance of responsibility and [Supercell Fan Content Policy](https://supercell.com/en/fan-content-policy/).
Do not commit ripped assets to public git without explicit project policy.
