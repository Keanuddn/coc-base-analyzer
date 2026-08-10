"""Synthetic base rendering (Phase 1c)."""

from renderer.domain_randomization import DomainRandomizationConfig, apply_domain_randomization
from renderer.isometric_renderer import IsometricRenderer, RenderResult

__all__ = [
    "DomainRandomizationConfig",
    "IsometricRenderer",
    "RenderResult",
    "apply_domain_randomization",
]
