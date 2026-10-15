"""The interface every provider adapter offers. Servers are found at the provider, never in a local state file:
the provider is the state."""

from __future__ import annotations

from typing import Protocol

from ..model import Server


class ProviderError(RuntimeError):
    """The provider refused, failed or could not be reached; the message says which and why."""


class Provider(Protocol):
    name: str

    def servers(self) -> list[Server]:
        """Every server this spec manages at the provider (also those beyond its count)."""
        ...

    def create(self, name: str, slot: int, public_keys: list[str], user_data: str) -> Server:
        """Create one server, with the public keys installed for root, and wait until it runs."""
        ...

    def rebuild(self, server: Server, public_keys: list[str], user_data: str) -> Server:
        """Install the spec's image anew on a server (same address), and wait until it runs."""
        ...

    def destroy(self, server: Server) -> None:
        """Delete one server."""
        ...
