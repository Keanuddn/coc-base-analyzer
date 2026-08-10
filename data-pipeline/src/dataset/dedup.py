"""Dataset-level deduplication for registry entries and screenshot images.

Registry harvesting (Phase 1a) deduplicates by URL string. This module compares
decoded layout identity (``layout_fingerprint`` / ``layout_content_key`` from
the link decoder) so the same base under different lang prefixes is recognized
once. Screenshot dedup uses SHA-256 over raw image bytes.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, Mapping

from harvesters.base_registry import BaseLink
from link_decoder.decoder import decode_base_link
from link_decoder.dedup import layout_content_key
from link_decoder.schema import DecodedBase

logger = logging.getLogger(__name__)

RegistryEntry = BaseLink | Mapping[str, Any]


def _entry_url(entry: RegistryEntry) -> str:
    if isinstance(entry, BaseLink):
        return entry.url
    return str(entry["url"])


def decode_registry_entry(entry: RegistryEntry) -> DecodedBase | None:
    """Decode a harvested registry entry URL, if decodable."""
    return decode_base_link(_entry_url(entry))


def is_duplicate_link(
    entry_a: RegistryEntry,
    entry_b: RegistryEntry,
    *,
    decoded_a: DecodedBase | None = None,
    decoded_b: DecodedBase | None = None,
) -> bool:
    """Return True when two entries refer to the same decoded layout identity."""
    if decoded_a is None:
        decoded_a = decode_registry_entry(entry_a)
    if decoded_b is None:
        decoded_b = decode_registry_entry(entry_b)

    key_a = layout_content_key(decoded_a) if decoded_a else None
    key_b = layout_content_key(decoded_b) if decoded_b else None

    if key_a is not None and key_b is not None:
        return key_a == key_b

    return _entry_url(entry_a) == _entry_url(entry_b)


def deduplicate_registry_entries(
    entries: list[RegistryEntry],
) -> tuple[list[RegistryEntry], list[RegistryEntry]]:
    """Return ``(unique, duplicates)`` comparing decoded layout content keys.

    Entries that fail to decode fall back to exact URL matching. The first
    occurrence of each content key (or URL) is kept.
    """
    seen_keys: dict[str, RegistryEntry] = {}
    seen_urls: set[str] = set()
    unique: list[RegistryEntry] = []
    duplicates: list[RegistryEntry] = []

    decode_cache: dict[str, DecodedBase | None] = {}

    for entry in entries:
        url = _entry_url(entry)
        if url not in decode_cache:
            decode_cache[url] = decode_base_link(url)

        decoded = decode_cache[url]
        content_key = layout_content_key(decoded) if decoded else None

        if content_key is not None:
            if content_key in seen_keys:
                duplicates.append(entry)
                logger.debug(
                    "Duplicate layout %s (same as %s)",
                    url,
                    _entry_url(seen_keys[content_key]),
                )
                continue
            seen_keys[content_key] = entry
            unique.append(entry)
            continue

        if url in seen_urls:
            duplicates.append(entry)
            continue

        seen_urls.add(url)
        unique.append(entry)

    return unique, duplicates


def image_content_hash(path: Path) -> str:
    """SHA-256 hex digest of raw image file bytes."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def deduplicate_images_by_hash(
    paths: list[Path],
) -> tuple[list[Path], list[Path]]:
    """Return ``(unique, duplicates)`` for screenshot/image paths by content hash."""
    seen: dict[str, Path] = {}
    unique: list[Path] = []
    duplicates: list[Path] = []

    for path in paths:
        if not path.is_file():
            logger.warning("Skipping missing image: %s", path)
            continue
        digest = image_content_hash(path)
        if digest in seen:
            duplicates.append(path)
            logger.debug("Duplicate image %s (same as %s)", path, seen[digest])
            continue
        seen[digest] = path
        unique.append(path)

    return unique, duplicates
