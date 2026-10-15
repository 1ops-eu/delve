"""Specs: what is valid, environment references, pools, and public keys only."""

from __future__ import annotations

from pathlib import Path

import pytest

from delve.spec import SpecError, load


def test_a_pool_names_its_slots(spec_file) -> None:  # type: ignore[no-untyped-def]
    s = load(spec_file(3), environ={})
    assert s.names() == [(1, "lab-1"), (2, "lab-2"), (3, "lab-3")]
    assert load(spec_file(1), environ={}).names() == [(1, "lab")]


def test_environment_references(tmp_path: Path) -> None:
    (tmp_path / "k.pub").write_text("ssh-ed25519 AAA k\n")
    p = tmp_path / "s.yaml"
    p.write_text(
        "kind: servers\nmeta: {name: x}\nprovider: {name: ovh, project: '${env:PROJ}'}\n"
        "servers: {name: x, type: b3-8, image: Ubuntu 24.04, location: GRA11, ssh_keys: [k.pub]}\n"
    )
    assert load(p, environ={"PROJ": "abc123"}).provider.project == "abc123"
    with pytest.raises(SpecError, match=r"\$\{env:PROJ\} is not set"):
        load(p, environ={})


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (("kind: servers", "kind: server"), "kind"),
        (("name: hetzner", "name: aws"), "provider.name"),
        (("count: 2", "count: 0"), "servers.count"),
        (("ops.pub", "ops"), "public key files"),
        (("location: fsn1", "location: fsn1\n  colour: red"), "colour"),
        (("meta: {name: lab", "meta: {name: Lab_1"), "meta.name"),
    ],
)
def test_invalid_specs(spec_file, change: tuple[str, str], message: str) -> None:  # type: ignore[no-untyped-def]
    p = spec_file(2)
    p.write_text(p.read_text().replace(*change))
    with pytest.raises(SpecError, match=message):
        load(p, environ={})


def test_public_keys_are_read_relative_to_the_spec(spec_file) -> None:  # type: ignore[no-untyped-def]
    p = spec_file(1)
    assert load(p, environ={}).public_keys(p.parent) == ["ssh-ed25519 AAAAC3Nza ops@example"]
    (p.parent / "ops.pub").unlink()
    with pytest.raises(SpecError, match="no file"):
        load(p, environ={}).public_keys(p.parent)
