"""What delve knows about a server and what a plan says to do."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


@dataclass
class Server:
    name: str
    slot: int
    id: str
    status: str
    ipv4: str | None
    ipv6: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "host": self.ipv4}


@dataclass
class Step:
    action: Literal["create", "keep", "surplus"]
    name: str
    slot: int
    server: Server | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"action": self.action, "name": self.name, "slot": self.slot,
                "server": self.server.to_dict() if self.server else None}  # fmt: skip


@dataclass
class Plan:
    spec: str
    provider: str
    steps: list[Step] = field(default_factory=list)

    @property
    def creates(self) -> list[Step]:
        return [s for s in self.steps if s.action == "create"]

    def to_dict(self) -> dict[str, Any]:
        return {"spec": self.spec, "provider": self.provider, "steps": [s.to_dict() for s in self.steps]}
