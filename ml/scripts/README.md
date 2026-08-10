# ML Scripts

## Label Review App

One-click pseudo-label review for regression screenshots (TH13/TH15/TH16).

```bash
cd ml && python scripts/label_review_app.py
# Open http://localhost:8765
```

### Buttons

| Button | Action |
|--------|--------|
| **Richtig** | Approve labels → saved to `_label_reviews.json`, included in training dataset |
| **Falsch** | 1st click: re-pseudo-label with conf=0.15 and show again. 2nd click: move to `_rejected/` and exclude |
| **Weiter** | Skip to next image without saving |
| **Dataset neu bauen** | Rebuild YOLO dataset with only approved regression labels |

Reviews are saved to `ml/tests/regression_set/_label_reviews.json`.
