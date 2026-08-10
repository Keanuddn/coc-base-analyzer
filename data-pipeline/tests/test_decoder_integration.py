"""End-to-end integration test: harvest-style link → decode → dedup."""

from __future__ import annotations

from link_decoder import (
    decode_base_link,
    deduplicate_decoded_bases,
    layout_content_key,
)

SAMPLE_LINK = (
    "https://link.clashofclans.com/en?action=OpenLayout&id="
    "TH16%3AHV%3AAAAABQAAAAL0Ea1Tjrx5cv7Sph99OYbe&ref=integration-test"
)
SAME_LAYOUT_DE_LINK = (
    "https://link.clashofclans.com/de?action=OpenLayout&id="
    "TH16%3AHV%3AAAAABQAAAAL0Ea1Tjrx5cv7Sph99OYbe"
)


def test_decode_sample_link_end_to_end() -> None:
    decoded = decode_base_link(SAMPLE_LINK)
    assert decoded is not None

    payload = decoded.to_dict()
    assert payload["town_hall_level"] == 16
    assert payload["village_type"] == "HV"
    assert payload["layout_slot"] == 2
    assert payload["collection_index"] == 5
    assert payload["layout_fingerprint"] == "f411ad538ebc7972fed2a61f7d3986de"
    assert payload["link_format"] == "open_layout"
    assert payload["buildings"] == []
    assert payload["traps"] == []
    assert "ref=" not in payload["link"]


def test_registry_urls_dedup_by_content_not_string() -> None:
    """Simulate two harvested URLs pointing at the same layout."""
    decoded_links = [decode_base_link(SAMPLE_LINK), decode_base_link(SAME_LAYOUT_DE_LINK)]
    assert all(d is not None for d in decoded_links)

    keys = [layout_content_key(d) for d in decoded_links if d]
    assert keys[0] == keys[1]

    unique, dupes = deduplicate_decoded_bases([d for d in decoded_links if d])
    assert len(unique) == 1
    assert len(dupes) == 1
