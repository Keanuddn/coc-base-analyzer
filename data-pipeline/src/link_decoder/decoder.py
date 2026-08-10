"""CoC share-link decoder stub (Phase 1b)."""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from link_decoder.schema import DecodedBase

logger = logging.getLogger(__name__)

COC_SHARE_LINK_RE = re.compile(
    r"^https://link\.clashofclans\.com/(?P<payload>[A-Za-z0-9+/=_\-]+)$"
)

_failed_decodings: list[dict[str, str]] = []


def decode_base_link(link: str) -> DecodedBase | None:
    link = link.strip()
    if not link.startswith("https://"):
        link = "https://" + link.lstrip("/")

    parsed = urlparse(link)
    if parsed.netloc.lower() != "link.clashofclans.com":
        _log_failure(link, "invalid host — expected link.clashofclans.com")
        return None

    normalized = f"https://link.clashofclans.com/{parsed.path.lstrip('/')}"
    match = COC_SHARE_LINK_RE.match(normalized.split("?")[0])
    if not match:
        _log_failure(link, "URL does not match expected share-link pattern")
        return None

    payload = match.group("payload")
    logger.info(
        "Decode stub: accepted link (payload len=%d). "
        "TODO: implement reverse-engineered format parser in Phase 1b.",
        len(payload),
    )

    return DecodedBase(
        link=normalized,
        raw_payload=payload,
        warnings=["Decoder not implemented — Phase 1b TODO"],
    )


def get_failed_decodings() -> list[dict[str, str]]:
    return list(_failed_decodings)


def _log_failure(link: str, reason: str) -> None:
    record = {"link": link, "reason": reason}
    _failed_decodings.append(record)
    logger.warning("Failed to decode base link: %s — %s", link, reason)
