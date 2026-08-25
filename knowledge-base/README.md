# Knowledge base

All Clash of Clans facts used by the analyzer come from files in this folder
and from `data-pipeline/src/renderer/sprites/th_unlocks.yaml`. Do not ask a
language model for HP, DPS, range, or troop stats.

| File | What it holds |
|------|----------------|
| `SOURCES.md` | Citation list (wiki, SuperCell notes, Clash Ninja) |
| `buildings.yaml` | Per-YOLO-class **targeting / range** (sourced). No HP/DPS. |
| `../data-pipeline/src/renderer/sprites/th_unlocks.yaml` | Number available + max level by TH |

`buildings.yaml` marks `targets: unknown` when a page was not sourced yet
(Cloudflare on Fandom, or TH16+ merges). Fill those in before using them in
an attack plan.

Python loader: `ml/src/kb_buildings.py`.

Inference JSON (`ml/src/infer.py`) attaches `wiki_name`, `category`, `targets`,
and a `summary.defenses_targeting` rollup after the Town Hall gate.
