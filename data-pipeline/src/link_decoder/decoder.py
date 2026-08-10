"""CoC share-link decoder (Phase 1b).

Parses OpenLayout URLs into structural metadata. Building/trap placements
are NOT embedded in share links — they require game-client resolution or
screenshot-based rendering (Phase 1c).
"""

from __future__ import annotations

import logging

from link_decoder.format import (
    canonical_open_layout_url,
    is_copy_army_link,
    is_legacy_clan_link,
    normalize_share_link,
    parse_open_layout_link,
)
from link_decoder.schema import DecodedBase

logger = logging.getLogger(__name__)

DECODE_VERSION = "structural-1.0"

_failed_decodings: list[dict[str, str]] = []


def decode_base_link(link: str) -> DecodedBase | None:
    """Decode a link.clashofclans.com share URL.

    Returns structural metadata for OpenLayout links. ``buildings`` and
    ``traps`` are always empty — layout geometry is resolved server-side by
    Supercell, not encoded in the URL (verified via nschmeller/clash-bases).
    """
    raw = link
    link = normalize_share_link(link)

    if is_copy_army_link(link):
        _log_failure(raw, "CopyArmy link — not a base layout")
        return None

    if is_legacy_clan_link(link):
        _log_failure(
            raw,
            "legacy clan/tag/token format — no public decoder for this link type",
        )
        return None

    canonical = canonical_open_layout_url(link)
    if canonical is None:
        _log_failure(raw, "unrecognized link.clashofclans.com format")
        return None

    payload = parse_open_layout_link(canonical)
    if payload is None:
        _log_failure(raw, "OpenLayout id failed structural validation")
        return None

    warnings = [
        "Building/trap placements are not encoded in OpenLayout share links. "
        "Use Phase 1c rendering or in-game import for geometry."
    ]

    logger.info(
        "Decoded layout link TH%d %s slot=%d index=%d fingerprint=%s",
        payload.town_hall,
        payload.village_type,
        payload.layout_slot,
        payload.collection_index,
        payload.layout_fingerprint[:16],
    )

    return DecodedBase(
        link=canonical,
        town_hall_level=payload.town_hall,
        village_type=payload.village_type,
        layout_slot=payload.layout_slot,
        collection_index=payload.collection_index,
        layout_fingerprint=payload.layout_fingerprint,
        link_format="open_layout",
        buildings=[],
        traps=[],
        raw_payload=payload.blob,
        decode_version=DECODE_VERSION,
        warnings=warnings,
    )


def decode_base_links(links: list[str]) -> list[DecodedBase | None]:
    """Batch decode — logs failures, never raises."""
    return [decode_base_link(link) for link in links]


def get_failed_decodings() -> list[dict[str, str]]:
    return list(_failed_decodings)


def clear_failed_decodings() -> None:
    _failed_decodings.clear()


def _log_failure(link: str, reason: str) -> None:
    record = {"link": link, "reason": reason}
    _failed_decodings.append(record)
    logger.warning("Failed to decode base link: %s — %s", link, reason)
