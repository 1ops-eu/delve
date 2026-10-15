"""Providers: one adapter per cloud, the same small interface for each (``base.Provider``)."""

from __future__ import annotations

from typing import Any

from ..spec import Spec
from .base import Provider, ProviderError


def provider_for(spec: Spec, client: Any = None) -> Provider:
    """The adapter the spec names; ``client`` replaces the SDK client (tests)."""
    if spec.provider.name == "hetzner":
        from .hetzner import Hetzner

        return Hetzner(spec, client)
    if spec.provider.name == "ovh":
        from .ovh import Ovh

        return Ovh(spec, client)
    raise ProviderError(f"no provider {spec.provider.name}")


__all__ = ["Provider", "ProviderError", "provider_for"]
