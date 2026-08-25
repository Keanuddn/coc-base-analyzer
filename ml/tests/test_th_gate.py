"""CPU tests for the inference Town Hall gate (no GPU / Ultralytics)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ML_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ML_SRC))

from th_gate import (  # noqa: E402
    apply_th_gate,
    gate_decision,
    load_th_gate_table,
    resolve_town_hall,
)


def _b(class_name: str, class_id: int, conf: float = 0.9, box=None) -> dict:
    return {
        "class": class_name,
        "class_id": class_id,
        "confidence": conf,
        "bbox_xyxy": list(box or [1.0, 2.0, 3.0, 4.0]),
    }


class TestSourcedMinTh(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.table = load_th_gate_table()

    def test_yolo_names_map_from_unlock_slugs(self) -> None:
        m = self.table.min_th_by_name
        self.assertEqual(m["superwizztower"], 18)
        self.assertEqual(m["super_wizard_tower"], 18)
        self.assertEqual(m["revengetower"], 18)
        self.assertEqual(m["mortar"], 3)
        self.assertEqual(m["ricochetcannon"], 16)
        self.assertEqual(m["firespitter"], 17)
        self.assertEqual(m["multigeartower"], 17)
        self.assertEqual(m["multiarchertower"], 16)
        self.assertNotIn("kingpad", m)

    def test_does_not_invent_min_th_for_unknown_class(self) -> None:
        action, remap = gate_decision("not_a_real_building", 15, self.table)
        self.assertEqual(action, "keep")
        self.assertIsNone(remap)


class TestResolveTownHall(unittest.TestCase):
    def test_cli_override_wins(self) -> None:
        buildings = [_b("th18", 31, 0.99)]
        th, src = resolve_town_hall(buildings, cli_th=15)
        self.assertEqual(th, 15)
        self.assertEqual(src, "cli")

    def test_detects_th15_box(self) -> None:
        buildings = [_b("th15", 28, 0.8), _b("mortar", 8, 0.9)]
        th, src = resolve_town_hall(buildings, cli_th=None)
        self.assertEqual(th, 15)
        self.assertEqual(src, "detection")

    def test_th13_only_is_unknown(self) -> None:
        buildings = [_b("th13", 12, 0.99), _b("wizztower", 14)]
        th, src = resolve_town_hall(buildings, cli_th=None)
        self.assertIsNone(th)
        self.assertEqual(src, "unknown")

    def test_no_hall_is_unknown(self) -> None:
        buildings = [_b("wizztower", 14), _b("superwizztower", 25)]
        th, src = resolve_town_hall(buildings, cli_th=None)
        self.assertIsNone(th)
        self.assertEqual(src, "unknown")


class TestApplyThGateTh15(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.table = load_th_gate_table()

    def test_superwizztower_becomes_wizztower_revenge_dropped_mortar_kept(self) -> None:
        super_box = [10.0, 20.0, 30.0, 40.0]
        buildings = [
            _b("superwizztower", 25, 0.91, super_box),
            _b("revengetower", 24, 0.88, [50.0, 60.0, 70.0, 80.0]),
            _b("mortar", 8, 0.77, [90.0, 100.0, 110.0, 120.0]),
            _b("wizztower", 14, 0.66, [1.0, 1.0, 2.0, 2.0]),
        ]
        gate = apply_th_gate(
            buildings,
            town_hall=15,
            town_hall_source="cli",
            table=self.table,
        )
        names = [b["class"] for b in gate.buildings]
        self.assertTrue(gate.applied)
        self.assertNotIn("superwizztower", names)
        self.assertEqual(names.count("wizztower"), 2)
        self.assertNotIn("revengetower", names)
        self.assertIn("mortar", names)
        remapped = next(b for b in gate.buildings if b["bbox_xyxy"] == super_box)
        self.assertEqual(remapped["class"], "wizztower")
        self.assertEqual(remapped["class_id"], self.table.class_id_by_name["wizztower"])
        self.assertEqual(remapped["confidence"], 0.91)
        self.assertEqual(gate.remapped, 1)
        self.assertEqual(gate.dropped, 1)

    def test_unknown_th_does_not_drop_or_remap(self) -> None:
        buildings = [_b("superwizztower", 25), _b("revengetower", 24)]
        gate = apply_th_gate(
            buildings,
            town_hall=None,
            town_hall_source="unknown",
            table=self.table,
        )
        self.assertFalse(gate.applied)
        self.assertEqual([b["class"] for b in gate.buildings], ["superwizztower", "revengetower"])

    def test_th18_keeps_superwizztower(self) -> None:
        buildings = [_b("superwizztower", 25), _b("revengetower", 24)]
        gate = apply_th_gate(
            buildings,
            town_hall=18,
            town_hall_source="cli",
            table=self.table,
        )
        names = [b["class"] for b in gate.buildings]
        self.assertEqual(names, ["superwizztower", "revengetower"])
        self.assertEqual(gate.remapped, 0)
        self.assertEqual(gate.dropped, 0)


if __name__ == "__main__":
    unittest.main()
