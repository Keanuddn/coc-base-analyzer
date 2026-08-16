"""Tests for keremberke box proposals in the FastAPI canvas labeler."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ML_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ML_ROOT / "scripts"))
sys.path.insert(0, str(ML_ROOT / "src"))

import manual_label_server as mls  # noqa: E402


def _tmp_session(directory: Path) -> mls.LabelSession:
    img_dir = directory / "th15"
    img_dir.mkdir(parents=True)
    img_path = img_dir / "war_base.png"
    Image.new("RGB", (64, 64), color=(40, 80, 40)).save(img_path)
    return mls.LabelSession(
        images=[img_path],
        regression_dir=directory,
        labels_dir=directory / "labels",
    )


class TestYoloLinesToBoxes(unittest.TestCase):
    def test_drops_deprecated_hero_pads(self) -> None:
        # keremberke: 7=kingpad, 3=canon
        lines = ["7 0.50 0.50 0.10 0.10", "3 0.40 0.40 0.12 0.12", "9 0.20 0.20 0.08 0.08"]
        boxes = mls.yolo_lines_to_boxes(lines)
        assert [b[0] for b in boxes] == [3]
        assert boxes[0][1:] == (0.40, 0.40, 0.12, 0.12)


class TestProposalSession(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.session = _tmp_session(Path(self._tmp.name))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_accept_all_merges_proposals_into_boxes(self) -> None:
        self.session.proposals = [(3, 0.5, 0.5, 0.1, 0.1), (8, 0.2, 0.3, 0.05, 0.05)]
        self.session.accept_all_proposals()
        assert self.session.boxes == [(3, 0.5, 0.5, 0.1, 0.1), (8, 0.2, 0.3, 0.05, 0.05)]
        assert self.session.proposals == []

    def test_delete_individual_proposal_and_confirmed_box(self) -> None:
        self.session.boxes = [(3, 0.5, 0.5, 0.1, 0.1)]
        self.session.proposals = [(8, 0.2, 0.2, 0.1, 0.1), (14, 0.3, 0.3, 0.1, 0.1)]
        self.session.delete_item("proposal", 0)
        assert [b[0] for b in self.session.proposals] == [14]
        self.session.delete_item("box", 0)
        assert self.session.boxes == []

    def test_load_proposals_uses_runner_and_keeps_existing_boxes(self) -> None:
        self.session.boxes = [(3, 0.1, 0.1, 0.05, 0.05)]

        def fake_runner(image_path: Path, conf: float) -> list[mls.Box]:
            assert image_path.name == "war_base.png"
            assert conf == mls.PROPOSAL_CONF
            return [(8, 0.4, 0.4, 0.1, 0.1), (7, 0.9, 0.9, 0.1, 0.1)]

        self.session.load_proposals(runner=fake_runner)
        assert self.session.boxes == [(3, 0.1, 0.1, 0.05, 0.05)]
        # runner may return deprecated ids; session still filters
        assert [b[0] for b in self.session.proposals] == [8]

    def test_state_marks_proposals_distinctly(self) -> None:
        self.session.proposals = [(3, 0.5, 0.5, 0.1, 0.1)]
        state = self.session.to_state()
        assert state["proposals"][0]["proposed"] is True
        assert state["proposals"][0]["color"] == mls.PROPOSAL_COLOR
        assert state["proposal_conf"] == mls.PROPOSAL_CONF


if __name__ == "__main__":
    unittest.main()
