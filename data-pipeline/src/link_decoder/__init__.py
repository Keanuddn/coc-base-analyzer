"""CoC share-link decoder (Phase 1b)."""

from link_decoder.decoder import (
    clear_failed_decodings,
    decode_base_link,
    decode_base_links,
    get_failed_decodings,
)
from link_decoder.dedup import deduplicate_decoded_bases, layout_content_key
from link_decoder.schema import BuildingPlacement, DecodedBase, TrapPlacement

__all__ = [
    "BuildingPlacement",
    "DecodedBase",
    "TrapPlacement",
    "clear_failed_decodings",
    "decode_base_link",
    "decode_base_links",
    "deduplicate_decoded_bases",
    "get_failed_decodings",
    "layout_content_key",
]
