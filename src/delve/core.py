"""What delve does with a spec and a provider: plan, apply (create what is missing), rebuild, destroy, status.
The commands of the CLI only adapt this.

Semantics: capability=delve
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .guard import require_sudo
from .model import Plan, Server, Step
from .providers.base import Provider
from .spec import Spec
from .ssh import forget_host, wait_for_ssh


class SelectionError(LookupError):
    """A slot the spec does not have, or a server that does not exist (yet)."""


def user_data(public_keys: list[str]) -> str:
    """First-boot script installing the public keys for root; providers differ in what they inject, this does not."""
    lines = ["#!/bin/bash", "# delve: install the spec's public keys for root", "mkdir -p /root/.ssh",
             "chmod 700 /root/.ssh"]  # fmt: skip
    for pk in public_keys:
        q = pk.replace("'", "")
        keys = "/root/.ssh/authorized_keys"
        lines.append(f"grep -qxF '{q}' {keys} 2>/dev/null || echo '{q}' >> {keys}")
    lines += ["chmod 600 /root/.ssh/authorized_keys", "chown -R root:root /root/.ssh"]
    return "\n".join(lines) + "\n"


def plan(spec: Spec, provider: Provider) -> Plan:
    existing = {s.name: s for s in provider.servers()}
    p = Plan(spec=spec.meta.name, provider=provider.name)
    wanted = dict(spec.names())
    for slot, name in spec.names():
        p.steps.append(Step("keep" if name in existing else "create", name, slot, existing.get(name)))
    for name, server in sorted(existing.items()):
        if name not in wanted.values():
            p.steps.append(Step("surplus", name, server.slot, server))
    return p


def apply(spec: Spec, provider: Provider, base: Path, geteuid: Callable[[], int] | None = None) -> Plan:
    """Create every server the spec has and the provider does not; nothing else changes. Creating buys
    resources, so it needs sudo; a plan with nothing to create needs none."""
    p = plan(spec, provider)
    if p.creates:
        require_sudo("delve apply (creating " + ", ".join(s.name for s in p.creates) + ")", geteuid)
        keys = spec.public_keys(base)
        for step in p.creates:
            step.server = provider.create(step.name, step.slot, keys, user_data(keys))
    return p


def select(spec: Spec, servers: list[Server], slot: int | None) -> list[Server]:
    if slot is not None and slot not in dict(spec.names()):
        raise SelectionError(f"the spec has no slot {slot} (count {spec.servers.count})")
    mine = [s for s in servers if s.slot in dict(spec.names())]
    chosen = [s for s in mine if slot is None or s.slot == slot]
    if not chosen:
        raise SelectionError("no such server at the provider; run delve apply first")
    return chosen


def rebuild(
    spec: Spec,
    provider: Provider,
    base: Path,
    slot: int | None = None,
    wait_ssh: bool = False,
    ssh_key: str | None = None,
    ssh_timeout_s: float = 300,
) -> list[Server]:
    """Install the image anew (same addresses, fresh disk); optionally wait until root logs in over SSH."""
    keys = spec.public_keys(base)
    out = []
    for s in select(spec, provider.servers(), slot):
        fresh = provider.rebuild(s, keys, user_data(keys))
        if fresh.ipv4:
            forget_host(fresh.ipv4)
            if wait_ssh:
                wait_for_ssh(fresh.ipv4, key=ssh_key, timeout_s=ssh_timeout_s)
        out.append(fresh)
    return out


def destroy(spec: Spec, provider: Provider, slot: int | None = None) -> list[Server]:
    """Delete the spec's servers (or one slot); servers beyond the count go too when no slot is given."""
    servers = provider.servers()
    chosen = servers if slot is None else select(spec, servers, slot)
    for s in chosen:
        provider.destroy(s)
    return chosen


def status(provider: Provider) -> list[Server]:
    return provider.servers()
