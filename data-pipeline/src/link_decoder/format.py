"""OpenLayout share-link format parsing.

Reverse-engineered from community validation work in
https://github.com/nschmeller/clash-bases (scripts/validate-bases.py).

Layout links are opaque server-side identifiers — the 24-byte payload
does NOT contain building coordinates. See docs/DATA_STRATEGY.md.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

EXPECTED_BLOB_CHARS = 32
EXPECTED_PAYLOAD_BYTES = 24
ALLOWED_SLOTS = frozenset({1, 2, 3})
ALLOWED_VILLAGES = frozenset({"HV", "WB"})

# Lang prefix is cosmetic; Supercell serves the same landing page for all.
OPEN_LAYOUT_URL_RE = re.compile(
    r"^https://link\.clashofclans\.com/(?P<lang>[a-z]{2})/?\?"
    r"action=OpenLayout&id="
    r"TH(?P<th>\d{1,2})%3A(?P<village>HV|WB)%3A(?P<blob>[A-Za-z0-9_\-]{32})"
    r"(?:&.*)?$"
)

COPY_ARMY_URL_RE = re.compile(
    r"^https://link\.clashofclans\.com/(?P<lang>[a-z]{2})/?\?"
    r"action=CopyArmy&army="
)


@dataclass(frozen=True, slots=True)
class LayoutPayload:
    """Decoded 24-byte OpenLayout identifier."""

    town_hall: int
    village_type: str
    blob: str
    collection_index: int
    layout_slot: int
    layout_fingerprint: str  # hex of bytes 8..24 (HMAC tag)


def normalize_share_link(link: str) -> str:
    """Strip whitespace and ensure https scheme."""
    link = link.strip()
    if not link.startswith(("http://", "https://")):
        link = "https://" + link.lstrip("/")
    if link.startswith("http://"):
        link = "https://" + link[len("http://") :]
    return link


def canonical_open_layout_url(link: str) -> str | None:
    """Return a normalized OpenLayout URL without cosmetic query params."""
    link = normalize_share_link(link)
    parsed = urlparse(link)
    if parsed.netloc.lower() != "link.clashofclans.com":
        return None

    params = parse_qs(parsed.query, keep_blank_values=False)
    action = (params.get("action") or [None])[0]
    layout_id = (params.get("id") or [None])[0]
    if action != "OpenLayout" or not layout_id:
        return None

    layout_id = unquote(layout_id)
    parts = layout_id.split(":")
    if len(parts) != 3:
        return None
    th_str, village, blob = parts
    if not th_str.startswith("TH") or village not in ALLOWED_VILLAGES:
        return None
    th = th_str[2:]
    if not th.isdigit() or len(blob) != EXPECTED_BLOB_CHARS:
        return None

    lang = parsed.path.strip("/").split("/")[0] if parsed.path.strip("/") else "en"
    if len(lang) != 2:
        lang = "en"

    encoded_id = f"TH{th}%3A{village}%3A{blob}"
    return f"https://link.clashofclans.com/{lang}?action=OpenLayout&id={encoded_id}"


def b64url_decode(blob: str) -> bytes:
    pad = "=" * ((4 - len(blob) % 4) % 4)
    return base64.urlsafe_b64decode(blob + pad)


def decode_layout_payload(blob: str, town_hall: int, village_type: str) -> LayoutPayload:
    payload = b64url_decode(blob)
    if len(payload) != EXPECTED_PAYLOAD_BYTES:
        raise ValueError(
            f"expected {EXPECTED_PAYLOAD_BYTES}-byte payload, got {len(payload)}"
        )

    collection_index = int.from_bytes(payload[0:4], "big")
    layout_slot = int.from_bytes(payload[4:8], "big")
    tag = payload[8:24]

    if layout_slot not in ALLOWED_SLOTS:
        raise ValueError(f"layout slot {layout_slot} not in {sorted(ALLOWED_SLOTS)}")

    return LayoutPayload(
        town_hall=town_hall,
        village_type=village_type,
        blob=blob,
        collection_index=collection_index,
        layout_slot=layout_slot,
        layout_fingerprint=tag.hex(),
    )


def parse_open_layout_link(link: str) -> LayoutPayload | None:
    """Parse a verified OpenLayout URL into structural metadata."""
    canonical = canonical_open_layout_url(link)
    if canonical is None:
        return None

    match = OPEN_LAYOUT_URL_RE.match(canonical)
    if match is None:
        return None

    th = int(match.group("th"))
    village = match.group("village")
    blob = match.group("blob")

    try:
        return decode_layout_payload(blob, th, village)
    except (ValueError, base64.binascii.Error):
        return None


def is_copy_army_link(link: str) -> bool:
    link = normalize_share_link(link)
    return bool(COPY_ARMY_URL_RE.match(link))


def is_legacy_clan_link(link: str) -> bool:
    """Detect pre-OpenLayout clan/tag/token query format (no layout payload)."""
    link = normalize_share_link(link)
    parsed = urlparse(link)
    if parsed.netloc.lower() != "link.clashofclans.com":
        return False
    params = parse_qs(parsed.query)
    return "clan" in params and "tag" in params and "token" in params
