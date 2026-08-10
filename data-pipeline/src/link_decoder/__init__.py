"""CoC share-link decoder (Phase 1b)."""

from link_decoder.decoder import decode_base_link
from link_decoder.schema import BuildingPlacement, DecodedBase, TrapPlacement

__all__ = [
    "BuildingPlacement",
    "DecodedBase",
    "TrapPlacement",
    "decode_base_link",
]
