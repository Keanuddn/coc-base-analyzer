# ML Scripts

## Screenshot analyzer (local HTTP)

Upload a war-base screenshot in the browser. Same JSON as `src/infer.py` — building
list plus targeting buckets. Not an attack planner.

```bash
cd ml && ./scripts/run_analyze.sh
# Open http://127.0.0.1:8767
```

Optional Town Hall 14–18 in the form (same as `infer.py --th`). First request loads
YOLO weights (`runs/coc_yolo_v9/weights/best.pt`) and can take a while.
After analyze, the page shows the screenshot with detection boxes — that is how
you check whether JSON matches the image. Counts over the sourced wiki maximum
(`th_unlocks.yaml`) are red. CLI equivalent:

```bash
.venv/bin/python src/infer.py path/to/base.png \
  --weights runs/coc_yolo_v9/weights/best.pt --th 16 \
  --overlay overlay.jpg -o out.json
```

## Label Review App

One-click pseudo-label review for regression screenshots (TH13/TH15/TH16).

```bash
cd ml && python scripts/label_review_app.py
# Open http://localhost:8765
```

Deprecated hero-pad classes (`kingpad`, `queenpad`, `rcpad`, `wardenpad`) are hidden
in the UI and filtered from pseudo-labels by default.

### Buttons

| Button | Action |
|--------|--------|
| **Richtig** | Approve labels → saved to `_label_reviews.json`, included in training dataset |
| **Falsch** | 1st click: re-pseudo-label with conf=0.35 (no hero pads) and show again. 2nd click: move to `_rejected/` and exclude |
| **Weiter** | Skip to next image without saving |
| **Dataset neu bauen** | Rebuild YOLO dataset with only approved regression labels |

Reviews are saved to `ml/tests/regression_set/_label_reviews.json`.

### Pseudo-label CLI

```bash
cd ml && python -m src.pseudo_label --conf 0.35
# Optional: --include-deprecated to keep kingpad/queenpad/rcpad/wardenpad
```

### Resource / army recall check

After `coc_yolo_v9` finishes (do **not** run this on MPS while training):

```bash
cd ml
.venv/bin/python src/eval_resource_army.py --conf 0.25
```

Wiki vs YOLO-GT vs predictions for mines, collectors, drill, army camps, and
1-count army buildings. Overlay: `ml/runs/coc_yolo_v9/eval/overlays/synthetic_0003.jpg`.
`--counts-only` skips the GPU and prints wiki vs GT only.

### Training strategy (small dataset)

Prefer **synthetic-only training** first when you have fewer than ~20 manually
reviewed real screenshots. Real TH15/16 pseudo-labels from the keremberke baseline
are noisy; only add approved regression labels after review, or stay synthetic-only
until manual labeling catches up. See `docs/DATA_STRATEGY.md`.
