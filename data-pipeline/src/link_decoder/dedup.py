"""Content-based deduplication for decoded layouts.

Registry URL dedup (Phase 1a) treats different lang prefixes or tracking
params as distinct URLs. This module fingerprints the decoded layout identity
(HMAC tag + TH + village type) so the same base is recognized once.
"""

from __future__ import annotations

from link_decoder.schema import DecodedBase


def layout_content_key(decoded: DecodedBase) -> str | None:
    """Stable fingerprint for a layout regardless of URL cosmetics."""
    if (
        decoded.layout_fingerprint
        and decoded.town_hall_level is not None
        and decoded.village_type
    ):
        return (
            f"TH{decoded.town_hall_level}:"
            f"{decoded.village_type}:"
            f"{decoded.layout_fingerprint}"
        )
    return None


def deduplicate_decoded_bases(
    bases: list[DecodedBase],
) -> tuple[list[DecodedBase], list[DecodedBase]]:
    """Return (unique, duplicates) comparing decoded layout identity."""
    seen: dict[str, DecodedBase] = {}
    unique: list[DecodedBase] = []
    duplicates: list[DecodedBase] = []

    for base in bases:
        key = layout_content_key(base)
        if key is None:
            unique.append(base)
            continue
        if key in seen:
            duplicates.append(base)
        else:
            seen[key] = base
            unique.append(base)

    return unique, duplicates
