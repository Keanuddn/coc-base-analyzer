# Building Sprites — Phase 1c Renderer

Isometric building WebP sprites for synthetic layout rendering.

## Source

**Primary:** [ClashKingInc/ClashKingAssets](https://github.com/ClashKingInc/ClashKingAssets)  
**CDN:** https://assets.clashk.ing  
**Local path:** `clashking/home-village/{building_slug}/level_{n}.webp`

Extracted from Supercell game files by the ClashKing community. The upstream repo is
GPL-3.0; the **image files remain Supercell intellectual property**.

## User responsibility

The project owner has accepted responsibility for using real in-game building art.
These assets must not be used commercially or in ways that violate
[Supercell's Fan Content Policy](https://supercell.com/en/fan-content-policy/).

**Attribution:** Credit [ClashKing](https://github.com/ClashKingInc/ClashKingAssets) /
https://assets.clashk.ing in project docs or about screen.

## Download

Sprites are **gitignored** (binary, copyrighted). Fetch locally:

```bash
cd data-pipeline/src/renderer/sprites
./download_clashking_sprites.sh
```

Requires `git`. Performs a sparse clone of `assets/buildings/home-village` (~4.8 MB, 472 WebP).

**No scenery/grass tiles** in that tree. Synthetic renders use procedural village grass
(`renderer/village_background.py`) — original checkerboard + forest ellipses, not game art.

## Building type mapping

See `building_type_map.yaml` for mapping from:

- ML label names (`canon`, `wizztower`, `ad`, …) in `docs/ARCHITECTURE.md`
- Decoder schema `building_type` strings
- ClashKing slug folders (`cannon`, `wizard_tower`, `air_defense`, …)

## Image format

| Property | Typical value |
|----------|----------------|
| Format | WebP, RGBA |
| View | Isometric (layout editor style) |
| Size | ~100–220 px bounding box |
| Naming | `level_{n}.webp` (1-based upgrade level) |

## Coverage (TH13–18 priority defenses)

| ClashKing slug | Levels | ML alias |
|----------------|--------|----------|
| `cannon` | 21 | `canon` |
| `mortar` | 18 | `mortar` |
| `inferno_tower` | 12 | `inferno` |
| `eagle_artillery` | 7 | `eagle` |
| `x-bow` | 13 | `xbow` |
| `scattershot` | 7 | `scattershot` |
| `monolith` | 5 | `monolith` |
| `spell_tower` | 4 | `spelltower` |
| `air_defense` | 16 | `ad` |
| `air_sweeper` | 7 | `airsweeper` |
| `bomb_tower` | 13 | `bombtower` |
| `wizard_tower` | 17 | `wizztower` |
| `clan_castle` | 14 | `clancastle` |
| `town_hall` | 18 | `th13` (TH15–18 skins) |
| `archer_tower` | 21 | `archertower` |
| `hidden_tesla` | 17 | `tesla` |
| `monolith` | 5 | `monolith` |
| `spell_tower` | 4 | `spelltower` |
| `firespitter` | 3 | `firespitter` |
| `ricochet_cannon` | 4 | `ricochetcannon` |
| `multi-archer_tower` | 4 | `multiarchertower` |
| `multi-gear_tower` | 3 | `multigeartower` |
| `revenge_tower` | 2 | `revengetower` |
| `super_wizard_tower` | 2 | `superwizztower` |
| `builder's_hut` | 8 | `builderhut` |
| `wall` | 19 | unlabeled |

Full catalogue: 512 files across all Home Village buildings.
