"""Shared fixtures: a spec on disk with a public key beside it, and a provider that keeps its servers in memory."""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from delve.model import Server

SPEC = """
kind: servers
meta: {name: lab, description: test pool}
provider: {name: hetzner}
servers:
  name: lab
  count: {count}
  type: cx22
  image: ubuntu-24.04
  location: fsn1
  ssh_keys: [ops.pub]
"""


@pytest.fixture
def spec_file(tmp_path: Path):  # type: ignore[no-untyped-def]
    def write(count: int = 2) -> Path:
        (tmp_path / "ops.pub").write_text("ssh-ed25519 AAAAC3Nza ops@example\n")
        p = tmp_path / "spec.yaml"
        p.write_text(SPEC.replace("{count}", str(count)))
        return p

    return write


class FakeProvider:
    """A provider in memory; records what was asked of it."""

    name = "fake"

    def __init__(self, existing: list[Server] | None = None) -> None:
        self.by_name = {s.name: s for s in existing or []}
        self.calls: list[tuple[str, str]] = []
        self.user_data: list[str] = []
        self._ids = itertools.count(100)

    def servers(self) -> list[Server]:
        return sorted(self.by_name.values(), key=lambda s: s.slot)

    def create(self, name: str, slot: int, public_keys: list[str], user_data: str) -> Server:
        self.calls.append(("create", name))
        self.user_data.append(user_data)
        s = Server(name=name, slot=slot, id=str(next(self._ids)), status="running", ipv4=f"192.0.2.{slot}")
        self.by_name[name] = s
        return s

    def rebuild(self, server: Server, public_keys: list[str], user_data: str) -> Server:
        self.calls.append(("rebuild", server.name))
        self.user_data.append(user_data)
        return server

    def destroy(self, server: Server) -> None:
        self.calls.append(("destroy", server.name))
        del self.by_name[server.name]


@pytest.fixture
def fake() -> FakeProvider:
    return FakeProvider()
