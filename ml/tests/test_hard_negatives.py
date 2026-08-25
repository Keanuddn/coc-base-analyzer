"""Export background/relabel crops without YOLO."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ML_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ML_SRC))

from hard_negatives import box_to_yolo, export_from_selection  # noqa: E402


class TestBoxToYolo(unittest.TestCase):
    def test_centered_box(self) -> None:
        cx, cy, bw, bh = box_to_yolo([10, 10, 30, 30], (0, 0, 40, 40))
        self.assertAlmostEqual(cx, 0.5)
        self.assertAlmostEqual(cy, 0.5)
        self.assertAlmostEqual(bw, 0.5)
        self.assertAlmostEqual(bh, 0.5)


class TestExport(unittest.TestCase):
    def test_writes_empty_and_relabel(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "th18_fake.png"
            Image.new("RGB", (200, 120), color=(20, 40, 80)).save(src)
            selection = root / "selection.yaml"
            selection.write_text(
                "source_image: th18_fake.png\n"
                "background:\n"
                "  - {id: water, xyxy: [0, 0, 40, 40], reason: test}\n"
                "relabel:\n"
                "  - {id: sweeper, xyxy: [80, 40, 120, 80], pad: 4, class: airsweeper}\n",
                encoding="utf-8",
            )
            written = export_from_selection(
                selection_path=selection,
                class_names=["ad", "airsweeper"],
            )
            self.assertEqual(len(written), 2)
            empty = next(p for p in written if p.stem.endswith("water"))
            self.assertEqual(empty.with_suffix(".txt").read_text(encoding="utf-8"), "")
            relabel = next(p for p in written if p.stem.endswith("sweeper"))
            line = relabel.with_suffix(".txt").read_text(encoding="utf-8").strip()
            self.assertTrue(line.startswith("1 "))


if __name__ == "__main__":
    unittest.main()
