"""Every active YOLO class must have a knowledge-base row."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ML_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ML_SRC))

from kb_buildings import load_building_kb, targets_for  # noqa: E402
from model_utils import active_class_names  # noqa: E402


class TestBuildingKb(unittest.TestCase):
    def test_every_active_class_has_a_row(self) -> None:
        kb = load_building_kb()
        missing = [name for name in active_class_names() if name not in kb]
        self.assertEqual(missing, [])

    def test_air_defense_is_air_only(self) -> None:
        self.assertEqual(targets_for("ad"), ["air"])

    def test_cannon_is_ground_only(self) -> None:
        self.assertEqual(targets_for("canon"), ["ground"])

    def test_legacy_th13_stays_unknown(self) -> None:
        self.assertEqual(targets_for("th13"), "unknown")

    def test_tesla_is_ground_and_air(self) -> None:
        self.assertEqual(targets_for("tesla"), ["ground", "air"])


class TestEnrichAndSummary(unittest.TestCase):
    def test_air_defense_gets_wiki_fields(self) -> None:
        from kb_buildings import enrich_building

        out = enrich_building({"class": "ad", "class_id": 0, "confidence": 0.9, "bbox_xyxy": [0, 0, 1, 1]})
        self.assertEqual(out["wiki_name"], "Air Defense")
        self.assertEqual(out["category"], "defense")
        self.assertEqual(out["targets"], ["air"])
        self.assertEqual(out["range_tiles"], 10)

    def test_unknown_class_does_not_invent_targets(self) -> None:
        from kb_buildings import enrich_building

        out = enrich_building({"class": "not_in_kb", "class_id": 99, "confidence": 0.1, "bbox_xyxy": [0, 0, 1, 1]})
        self.assertEqual(out["targets"], "unknown")
        self.assertEqual(out["category"], "unknown")

    def test_summary_splits_air_and_ground_defenses(self) -> None:
        from kb_buildings import attach_knowledge_base

        payload = attach_knowledge_base(
            {
                "buildings": [
                    {"class": "ad", "class_id": 0, "confidence": 0.9, "bbox_xyxy": [0, 0, 1, 1]},
                    {"class": "canon", "class_id": 3, "confidence": 0.9, "bbox_xyxy": [0, 0, 1, 1]},
                    {"class": "xbow", "class_id": 15, "confidence": 0.9, "bbox_xyxy": [0, 0, 1, 1]},
                    {"class": "goldmine", "class_id": 35, "confidence": 0.9, "bbox_xyxy": [0, 0, 1, 1]},
                ]
            }
        )
        targeting = payload["summary"]["defenses_targeting"]
        self.assertEqual(targeting["air"], 1)
        self.assertEqual(targeting["ground"], 1)
        self.assertEqual(targeting["unknown"], 1)  # X-Bow mode_dependent
        self.assertEqual(payload["summary"]["by_category"]["resource"], 1)


if __name__ == "__main__":
    unittest.main()
