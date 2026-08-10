"""Tests for dataset-level link and image deduplication."""

from __future__ import annotations

from pathlib import Path

import pytest

from dataset.dedup import (
    deduplicate_images_by_hash,
    deduplicate_registry_entries,
    image_content_hash,
    is_duplicate_link,
)
from harvesters.base_registry import BaseLink
from link_decoder.decoder import decode_base_link

TH12_WB = (
    "https://link.clashofclans.com/fr?action=OpenLayout&id="
    "TH12%3AWB%3AAAAAHgAAAAFy_S4-CzVCnBGBJfbJGxmp"
)
TH12_WB_DE = (
    "https://link.clashofclans.com/de?action=OpenLayout&id="
    "TH12%3AWB%3AAAAAHgAAAAFy_S4-CzVCnBGBJfbJGxmp"
)
TH12_HV = (
    "https://link.clashofclans.com/fr?action=OpenLayout&id="
    "TH12%3AHV%3AAAAAMwAAAAFTCL21qFteUBIQVqG2loMc"
)


def _link(url: str) -> BaseLink:
    return BaseLink(url=url, source="test", discovered_at="2026-08-10T12:00:00Z")


class TestIsDuplicateLink:
    def test_same_layout_different_lang_is_duplicate(self) -> None:
        assert is_duplicate_link(_link(TH12_WB), _link(TH12_WB_DE))

    def test_different_layouts_not_duplicate(self) -> None:
        assert not is_duplicate_link(_link(TH12_WB), _link(TH12_HV))

    def test_accepts_predecoded_bases(self) -> None:
        decoded_a = decode_base_link(TH12_WB)
        decoded_b = decode_base_link(TH12_WB_DE)
        assert decoded_a and decoded_b
        assert is_duplicate_link(
            _link(TH12_WB),
            _link(TH12_WB_DE),
            decoded_a=decoded_a,
            decoded_b=decoded_b,
        )


class TestDeduplicateRegistryEntries:
    def test_deduplicates_by_content_key(self) -> None:
        entries = [_link(TH12_WB), _link(TH12_WB_DE), _link(TH12_HV)]
        unique, duplicates = deduplicate_registry_entries(entries)
        assert len(unique) == 2
        assert len(duplicates) == 1

    def test_dict_entries_supported(self) -> None:
        entries = [
            {"url": TH12_WB, "source": "test"},
            {"url": TH12_WB_DE, "source": "test"},
        ]
        unique, duplicates = deduplicate_registry_entries(entries)
        assert len(unique) == 1
        assert len(duplicates) == 1


class TestImageDedup:
    def test_identical_files_deduplicated(self, tmp_path: Path) -> None:
        img_a = tmp_path / "a.png"
        img_b = tmp_path / "b.png"
        img_a.write_bytes(b"\x89PNG-same-content")
        img_b.write_bytes(b"\x89PNG-same-content")

        unique, duplicates = deduplicate_images_by_hash([img_a, img_b])
        assert len(unique) == 1
        assert len(duplicates) == 1
        assert image_content_hash(img_a) == image_content_hash(img_b)

    def test_different_files_kept(self, tmp_path: Path) -> None:
        img_a = tmp_path / "a.png"
        img_b = tmp_path / "b.png"
        img_a.write_bytes(b"\x89PNG-a")
        img_b.write_bytes(b"\x89PNG-b")

        unique, duplicates = deduplicate_images_by_hash([img_a, img_b])
        assert len(unique) == 2
        assert len(duplicates) == 0

    def test_missing_file_skipped(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing.png"
        unique, duplicates = deduplicate_images_by_hash([missing])
        assert unique == []
        assert duplicates == []
