# Empty village scenery backgrounds

User-provided Clash of Clans empty-village screenshots. The isometric renderer
composites synthetic buildings onto the playable 44×44 diamond in each photo.

Emulator hotkey overlays (`G`, `V`, `Z`, `C`, `Space`, and similar letter
circles) may be present. They are part of the capture and must **not** be
YOLO-labeled. Anniversary cakes and other map decorations in these shots are
background, not buildings.

| File | Scenery |
|------|---------|
| `ruins_temple.png` | Ancient ruins / temple courtyard |
| `primal.png` | Primal jungle (giant skull) |
| `anniversary_green.png` | Anniversary green forest |
| `classic_crystals.png` | Classic forest with pink crystals |
| `pixel_forest.png` | Pixel-art forest |
| `jungle_waterfall.png` | Jungle with waterfall |
| `classic_grass.png` | Classic home-village grass |
| `clan_war.png` | Clan war / volcanic (war map) |

Default synthetic generation picks a random `*.png` from this folder (this
README is ignored). `--flat-background` uses procedural grass instead. If this
folder has no PNGs, procedural grass is the fallback.
