"""Tests for YOLO dataset assembly (Phase 1d)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from dataset.build_dataset import (
    BuildDatasetConfig,
    assign_splits,
    build_yolo_dataset,
    infer_town_hall_level,
    write_data_yaml,
)
from dataset.dedup import deduplicate_registry_entries
from harvesters.base_registry import BaseLink

PIPELINE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PIPELINE_ROOT.parent
REGRESSION_DIR = REPO_ROOT / "ml" / "tests" / "regression_set"


def _write_minimal_yolo_pair(directory: Path, stem: str, class_id: int = 3) -> None:
    """Create a tiny PNG + valid YOLO label sidecar."""
    from PIL import Image

    img_path = directory / f"{stem}.png"
    lbl_path = directory / f"{stem}.txt"
    Image.new("RGB", (64, 64), color=(80, 120, 70)).save(img_path)
    lbl_path.write_text(f"{class_id} 0.5 0.5 0.2 0.2\n", encoding="utf-8")


@pytest.fixture
def synthetic_demo_dir(tmp_path: Path) -> Path:
    demo = tmp_path / "demo"
    demo.mkdir()
    _write_minimal_yolo_pair(demo, "sample_base")
    return demo


class TestInferTownHallLevel:
    def test_from_folder(self) -> None:
        assert infer_town_hall_level(Path("ml/tests/regression_set/th15/war_base.png")) == 15

    def test_from_filename_prefix(self) -> None:
        assert infer_town_hall_level(Path("_extras/th13_war_arena.png")) == 13

    def test_unknown(self) -> None:
        assert infer_town_hall_level(Path("misc/unknown.png")) is None


class TestBuildYoloDataset:
    def test_demo_produces_valid_yolo_structure(self, synthetic_demo_dir: Path, tmp_path: Path) -> None:
        output = tmp_path / "yolo_out"
        config = BuildDatasetConfig(
            output_dir=output,
            include_demo=True,
            include_regression=False,
            demo_dir=synthetic_demo_dir,
            render_synthetic_variants=False,
            train_ratio=0.5,
            val_ratio=0.25,
            test_ratio=0.25,
            seed=7,
        )
        result = build_yolo_dataset(config)

        assert result.data_yaml_path.is_file()
        assert result.report_path.is_file()

        data = yaml.safe_load(result.data_yaml_path.read_text(encoding="utf-8"))
        assert data["train"] == "train/images"
        assert data["val"] == "val/images"
        assert data["nc"] >= 16

        report = json.loads(result.report_path.read_text(encoding="utf-8"))
        assert report["totals"]["synthetic"] >= 1
        assert report["totals"]["labeled"] >= 1
        assert "town_hall_balance" in report

        train_images = list((output / "train" / "images").glob("*.png"))
        assert train_images, "Expected at least one training image"

        for split in ("train", "val", "test"):
            img_dir = output / split / "images"
            lbl_dir = output / split / "labels"
            if not img_dir.is_dir():
                continue
            for img in img_dir.glob("*.png"):
                lbl = lbl_dir / f"{img.stem}.txt"
                assert lbl.is_file(), f"Missing label for {img.name}"
                lines = lbl.read_text(encoding="utf-8").strip().splitlines()
                assert lines
                parts = lines[0].split()
                assert len(parts) == 5

    def test_regression_unlabeled_go_to_images_unlabeled(
        self,
        synthetic_demo_dir: Path,
        tmp_path: Path,
    ) -> None:
        if not REGRESSION_DIR.is_dir():
            pytest.skip("Regression set not present")

        output = tmp_path / "yolo_mixed"
        config = BuildDatasetConfig(
            output_dir=output,
            include_demo=True,
            include_regression=True,
            demo_dir=synthetic_demo_dir,
            regression_dir=REGRESSION_DIR,
            render_synthetic_variants=False,
            seed=11,
        )
        result = build_yolo_dataset(config)
        report = json.loads(result.report_path.read_text(encoding="utf-8"))

        assert report["totals"]["real"] >= 1
        assert report["totals"]["unlabeled"] >= 1
        assert report["unlabeled_real_images"]["warning"]

        unlabeled_dirs = list(output.glob("*/images_unlabeled"))
        assert unlabeled_dirs, "Expected images_unlabeled/ for real screenshots"
        assert any(d.glob("*.png") for d in unlabeled_dirs)

    def test_assign_splits_respects_seed(self, synthetic_demo_dir: Path) -> None:
        from dataset.build_dataset import DatasetSample

        samples = [
            DatasetSample(
                source_path=synthetic_demo_dir / f"s{i}.png",
                origin="synthetic",
                town_hall_level=15,
                has_labels=True,
            )
            for i in range(6)
        ]
        assign_splits(samples, train_ratio=0.5, val_ratio=0.25, test_ratio=0.25, seed=99)
        splits_a = [s.split for s in samples]

        for s in samples:
            s.split = None
        assign_splits(samples, train_ratio=0.5, val_ratio=0.25, test_ratio=0.25, seed=99)
        splits_b = [s.split for s in samples]
        assert splits_a == splits_b


class TestWriteDataYaml:
    def test_writes_names(self, tmp_path: Path) -> None:
        path = write_data_yaml(tmp_path)
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert payload["names"][0] == "ad"
        assert payload["names"][12] == "th13"


class TestRegistryDedupIntegration:
    def test_registry_content_dedup(self) -> None:
        url_a = (
            "https://link.clashofclans.com/fr?action=OpenLayout&id="
            "TH12%3AWB%3AAAAAHgAAAAFy_S4-CzVCnBGBJfbJGxmp"
        )
        url_b = url_a.replace("/fr?", "/de?")
        entries = [
            BaseLink(url=url_a, source="test", discovered_at="2026-08-10T12:00:00Z"),
            BaseLink(url=url_b, source="test", discovered_at="2026-08-10T12:01:00Z"),
        ]
        unique, dupes = deduplicate_registry_entries(entries)
        assert len(unique) == 1
        assert len(dupes) == 1
