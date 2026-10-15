"""The core against a provider in memory: plans, idempotent apply, the sudo guard, slots, rebuild and destroy."""

from __future__ import annotations

import pytest

from delve import core
from delve.guard import PurchaseRefused
from delve.model import Server
from delve.spec import load

ROOT = lambda: 0  # noqa: E731
USER = lambda: 1000  # noqa: E731


def test_apply_creates_what_is_missing_and_only_that(spec_file, fake) -> None:  # type: ignore[no-untyped-def]
    p = spec_file(2)
    s = load(p, environ={})
    first = core.apply(s, fake, p.parent, geteuid=ROOT)
    assert [(st.action, st.name) for st in first.steps] == [("create", "lab-1"), ("create", "lab-2")]
    again = core.apply(s, fake, p.parent, geteuid=USER)  # nothing to buy: no sudo needed
    assert [st.action for st in again.steps] == ["keep", "keep"]
    assert fake.calls == [("create", "lab-1"), ("create", "lab-2")]
    assert "ssh-ed25519 AAAAC3Nza ops@example" in fake.user_data[0]


def test_buying_needs_sudo(spec_file, fake) -> None:  # type: ignore[no-untyped-def]
    p = spec_file(1)
    with pytest.raises(PurchaseRefused, match="needs sudo"):
        core.apply(load(p, environ={}), fake, p.parent, geteuid=USER)
    assert fake.calls == []


def test_a_plan_shows_servers_beyond_the_count(spec_file, fake) -> None:  # type: ignore[no-untyped-def]
    fake.by_name["lab-3"] = Server(name="lab-3", slot=3, id="9", status="running", ipv4="192.0.2.3")
    p = core.plan(load(spec_file(2), environ={}), fake)
    assert [(st.action, st.name) for st in p.steps] == [("create", "lab-1"), ("create", "lab-2"), ("surplus", "lab-3")]


def test_rebuild_and_destroy_by_slot(spec_file, fake) -> None:  # type: ignore[no-untyped-def]
    p = spec_file(2)
    s = load(p, environ={})
    core.apply(s, fake, p.parent, geteuid=ROOT)
    assert [x.name for x in core.rebuild(s, fake, p.parent, slot=2)] == ["lab-2"]
    with pytest.raises(core.SelectionError, match="no slot 5"):
        core.rebuild(s, fake, p.parent, slot=5)
    assert [x.name for x in core.destroy(s, fake, slot=1)] == ["lab-1"]
    with pytest.raises(core.SelectionError, match="run delve apply first"):
        core.rebuild(s, fake, p.parent, slot=1)
    assert [x.name for x in core.destroy(s, fake)] == ["lab-2"]
    assert fake.calls[-3:] == [("rebuild", "lab-2"), ("destroy", "lab-1"), ("destroy", "lab-2")]


def test_user_data_installs_every_key_once() -> None:
    script = core.user_data(["ssh-ed25519 A one", "ssh-rsa B two"])
    assert script.startswith("#!/bin/bash\n")
    assert script.count("grep -qxF") == 2
