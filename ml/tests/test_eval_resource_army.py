"""CPU tests for resource/army wiki-vs-GT counting (no Ultralytics)."""

from __future__ import annotations

import sys
import unittest
from collections import Counter
from pathlib import Path

ML_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ML_SRC))

from eval_resource_army import (  # noqa: E402
    compare_focus,
    format_table,
    infer_th_from_path,
    parse_yolo_class_counts,
    wiki_count,
)


class TestParseYoloCounts(unittest.TestCase):
    def test_counts_named_classes(self) -> None:
        names = ["ad", "canon"] + [""] * 36 + ["armycamp"]
        names[38] = "armycamp"
        text = "38 0.50 0.50 0.20 0.20\n38 0.10 0.10 0.20 0.20\n3 0.2 0.2 0.1 0.1\n"
        counts = parse_yolo_class_counts(text, names)
        self.assertEqual(counts["armycamp"], 2)

    def test_skips_blank_and_comments(self) -> None:
        counts = parse_yolo_class_counts("# hi\n\n0 0.1 0.1 0.1 0.1\n", ["ad"])
        self.assertEqual(counts["ad"], 1)


class TestWikiCount(unittest.TestCase):
    def test_int_and_str_keys(self) -> None:
        unlocks = {"armycamp": {"count_by_th": {18: 4}}, "goldmine": {"count_by_th": {"15": 7}}}
        self.assertEqual(wiki_count(unlocks, "armycamp", 18), 4)
        self.assertEqual(wiki_count(unlocks, "goldmine", 15), 7)
        self.assertIsNone(wiki_count(unlocks, "missing", 18))


class TestCompareAndPath(unittest.TestCase):
    def test_compare_focus_rows(self) -> None:
        rows = compare_focus(
            wiki={"goldmine": 7, "armycamp": 4},
            gt=Counter({"goldmine": 7, "armycamp": 4}),
            pred=Counter({"goldmine": 6}),
            focus=("goldmine", "armycamp"),
        )
        self.assertEqual(rows[0], {"class": "goldmine", "wiki": 7, "gt": 7, "pred": 6})
        self.assertEqual(rows[1]["pred"], 0)

    def test_th_from_path(self) -> None:
        path = Path("/tmp/synthetic_v1/th18/synthetic_0003.png")
        self.assertEqual(infer_th_from_path(path), 18)

    def test_format_table_contains_headers(self) -> None:
        text = format_table([{"class": "armycamp", "wiki": 4, "gt": 4, "pred": 0}])
        self.assertIn("armycamp", text)
        self.assertIn("wiki", text)


if __name__ == "__main__":
    unittest.main()
