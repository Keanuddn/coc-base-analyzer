"""CPU tests: detection counts vs sourced wiki maxima (no YOLO)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ML_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ML_SRC))

from count_gate import attach_count_gate, compare_counts, load_count_table, wiki_max_for  # noqa: E402


class TestSourcedWikiMax(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.table = load_count_table()

    def test_builderhut_is_five_at_th18(self) -> None:
        maximum, _ = wiki_max_for("builderhut", 18, self.table)
        self.assertEqual(maximum, 5)

    def test_mortar_is_four_at_th18(self) -> None:
        maximum, _ = wiki_max_for("mortar", 18, self.table)
        self.assertEqual(maximum, 4)

    def test_yolo_merge_names_map(self) -> None:
        maximum, _ = wiki_max_for("ricochetcannon", 18, self.table)
        self.assertEqual(maximum, 3)
        maximum, _ = wiki_max_for("superwizztower", 18, self.table)
        self.assertEqual(maximum, 2)

    def test_does_not_invent_count_for_unknown_class(self) -> None:
        maximum, row = wiki_max_for("not_a_real_building", 18, self.table)
        self.assertIsNone(maximum)
        self.assertIsNone(row)

    def test_does_not_invent_th14_when_table_starts_at_15(self) -> None:
        maximum, row = wiki_max_for("builderhut", 14, self.table)
        self.assertIsNotNone(row)
        self.assertIsNone(maximum)


class TestCompareCounts(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.table = load_count_table()

    def test_over_max_builderhut(self) -> None:
        gate = compare_counts({"builderhut": 8, "mortar": 4}, 18, table=self.table)
        self.assertTrue(gate["applied"])
        over = {row["class"]: row for row in gate["over_max"]}
        self.assertEqual(over["builderhut"]["wiki_max"], 5)
        self.assertEqual(over["builderhut"]["excess"], 3)
        self.assertNotIn("mortar", over)

    def test_unknown_th_skips(self) -> None:
        gate = compare_counts({"builderhut": 8}, None, table=self.table)
        self.assertFalse(gate["applied"])
        self.assertEqual(gate["over_max"], [])

    def test_two_hall_boxes_collapse_to_one_cap(self) -> None:
        gate = compare_counts({"th18": 1, "th17": 1}, 18, table=self.table)
        over = {row["class"]: row for row in gate["over_max"]}
        self.assertEqual(over["town_hall"]["detected"], 2)
        self.assertEqual(over["town_hall"]["wiki_max"], 1)

    def test_merge_cap_noted_for_wizard_tower_at_th18(self) -> None:
        gate = compare_counts({"wizztower": 4}, 18, table=self.table)
        row = next(r for r in gate["rows"] if r["class"] == "wizztower")
        self.assertTrue(row["merge_cap"])
        self.assertEqual(row["status"], "over")
        self.assertEqual(row["wiki_max"], 2)


class TestAttach(unittest.TestCase):
    def test_reads_summary_and_town_hall(self) -> None:
        payload = attach_count_gate(
            {
                "town_hall": 18,
                "summary": {"by_class": {"builderhut": 8}},
                "buildings": [],
            }
        )
        self.assertEqual(payload["count_gate"]["over_max"][0]["class"], "builderhut")


if __name__ == "__main__":
    unittest.main()
