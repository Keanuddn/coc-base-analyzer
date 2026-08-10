# ML Scripts

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

### Training strategy (small dataset)

Prefer **synthetic-only training** first when you have fewer than ~20 manually
reviewed real screenshots. Real TH15/16 pseudo-labels from the keremberke baseline
are noisy; only add approved regression labels after review, or stay synthetic-only
until manual labeling catches up. See `docs/DATA_STRATEGY.md`.
