"""Unit tests for OpenLayout link decoder.

Test vectors sourced from:
- Supercell MCES War Bases blog (2019): TH12 layouts
- MonsieurSingh/ClashofClans_auto_loot README: TH15/TH16 layouts
- nschmeller/clash-bases validate-bases.py payload structure
"""

from __future__ import annotations

import pytest

from link_decoder.decoder import (
    clear_failed_decodings,
    decode_base_link,
    decode_base_links,
    get_failed_decodings,
)
from link_decoder.dedup import deduplicate_decoded_bases, layout_content_key

# Verified public layout links (Supercell blog + open-source READMEs)
TH12_WB_SUPPERCELL = (
    "https://link.clashofclans.com/fr?action=OpenLayout&id="
    "TH12%3AWB%3AAAAAHgAAAAFy_S4-CzVCnBGBJfbJGxmp"
)
TH12_HV_SUPPERCELL = (
    "https://link.clashofclans.com/fr?action=OpenLayout&id="
    "TH12%3AHV%3AAAAAMwAAAAFTCL21qFteUBIQVqG2loMc"
)
TH15_HV_MONSIEURSINGH = (
    "https://link.clashofclans.com/en?action=OpenLayout&id="
    "TH15%3AHV%3AAAAABQAAAALyqvTgqf3LVADJ1UxoSF49"
)

COPY_ARMY_LINK = (
    "https://link.clashofclans.com/en?action=CopyArmy&army="
    "u10x0-2x3s1x9-3x2"
)
LEGACY_CLAN_LINK = (
    "https://link.clashofclans.com/en?clan=abc&tag=XYZ&token=deadbeef"
)


@pytest.fixture(autouse=True)
def _clear_failure_log() -> None:
    clear_failed_decodings()
    yield
    clear_failed_decodings()


class TestOpenLayoutDecode:
    def test_th12_war_base_supercell(self) -> None:
        decoded = decode_base_link(TH12_WB_SUPPERCELL)
        assert decoded is not None
        assert decoded.town_hall_level == 12
        assert decoded.village_type == "WB"
        assert decoded.layout_slot == 1
        assert decoded.collection_index == 30
        assert decoded.layout_fingerprint == "72fd2e3e0b35429c118125f6c91b19a9"
        assert decoded.raw_payload == "AAAAHgAAAAFy_S4-CzVCnBGBJfbJGxmp"
        assert decoded.link_format == "open_layout"
        assert decoded.decode_version == "structural-1.0"
        assert decoded.buildings == []
        assert decoded.traps == []
        assert len(decoded.warnings) == 1

    def test_th12_home_village_supercell(self) -> None:
        decoded = decode_base_link(TH12_HV_SUPPERCELL)
        assert decoded is not None
        assert decoded.town_hall_level == 12
        assert decoded.village_type == "HV"
        assert decoded.layout_slot == 1
        assert decoded.collection_index == 51
        assert decoded.layout_fingerprint == "5308bdb5a85b5e50121056a1b696831c"

    def test_th15_home_village_monsieursingh(self) -> None:
        decoded = decode_base_link(TH15_HV_MONSIEURSINGH)
        assert decoded is not None
        assert decoded.town_hall_level == 15
        assert decoded.village_type == "HV"
        assert decoded.layout_slot == 2
        assert decoded.collection_index == 5
        assert decoded.layout_fingerprint == "f2aaf4e0a9fdcb5400c9d54c68485e3d"

    def test_url_with_tracking_params(self) -> None:
        link = TH12_WB_SUPPERCELL + "&ref=example.com&fbclid=IwAR123"
        decoded = decode_base_link(link)
        assert decoded is not None
        assert decoded.town_hall_level == 12
        assert "ref=" not in decoded.link
        assert "fbclid=" not in decoded.link

    def test_different_lang_same_layout(self) -> None:
        en_link = TH12_WB_SUPPERCELL.replace("/fr?", "/en?")
        decoded_fr = decode_base_link(TH12_WB_SUPPERCELL)
        decoded_en = decode_base_link(en_link)
        assert decoded_fr and decoded_en
        assert layout_content_key(decoded_fr) == layout_content_key(decoded_en)


class TestRejections:
    def test_copy_army_rejected(self) -> None:
        assert decode_base_link(COPY_ARMY_LINK) is None
        failures = get_failed_decodings()
        assert len(failures) == 1
        assert "CopyArmy" in failures[0]["reason"]

    def test_legacy_clan_link_rejected(self) -> None:
        assert decode_base_link(LEGACY_CLAN_LINK) is None
        failures = get_failed_decodings()
        assert len(failures) == 1
        assert "legacy" in failures[0]["reason"]

    def test_invalid_host_rejected(self) -> None:
        assert decode_base_link("https://evil.example/layout") is None

    def test_garbage_payload_rejected(self) -> None:
        bad = (
            "https://link.clashofclans.com/en?action=OpenLayout&id="
            "TH12%3AWB%3A" + "A" * 32
        )
        assert decode_base_link(bad) is None


class TestBatchDecode:
    def test_batch_does_not_crash_on_mixed_links(self) -> None:
        results = decode_base_links(
            [TH12_WB_SUPPERCELL, COPY_ARMY_LINK, "not-a-url", TH15_HV_MONSIEURSINGH]
        )
        assert len(results) == 4
        assert results[0] is not None
        assert results[1] is None
        assert results[2] is None
        assert results[3] is not None
        assert len(get_failed_decodings()) == 2


class TestContentDedup:
    def test_same_layout_different_urls_deduplicated(self) -> None:
        base_a = decode_base_link(TH12_WB_SUPPERCELL)
        base_b = decode_base_link(TH12_WB_SUPPERCELL.replace("/fr?", "/de?"))
        assert base_a and base_b

        unique, duplicates = deduplicate_decoded_bases([base_a, base_b])
        assert len(unique) == 1
        assert len(duplicates) == 1

    def test_different_layouts_not_deduplicated(self) -> None:
        base_a = decode_base_link(TH12_WB_SUPPERCELL)
        base_b = decode_base_link(TH12_HV_SUPPERCELL)
        assert base_a and base_b

        unique, duplicates = deduplicate_decoded_bases([base_a, base_b])
        assert len(unique) == 2
        assert len(duplicates) == 0
