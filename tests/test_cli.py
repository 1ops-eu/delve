"""The command line: one line of JSON for other tools, exit codes, and the guards (sudo, --yes)."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from delve import cli, guard
from delve.model import Server

from .conftest import FakeProvider


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> FakeProvider:
    p = FakeProvider([Server(name="lab-1", slot=1, id="1", status="running", ipv4="192.0.2.1")])
    monkeypatch.setattr(cli, "provider_for", lambda spec: p)
    return p


def test_rebuild_with_a_slot_prints_one_json_object(spec_file, provider) -> None:  # type: ignore[no-untyped-def]
    r = CliRunner().invoke(cli.app, ["rebuild", str(spec_file(2)), "--slot", "1", "--json"])
    assert r.exit_code == 0, r.output
    line = r.output.strip().splitlines()[-1]
    assert json.loads(line)["host"] == "192.0.2.1"
    assert provider.calls == [("rebuild", "lab-1")]


def test_ip_status_plan(spec_file, provider) -> None:  # type: ignore[no-untyped-def]
    p = str(spec_file(2))
    assert CliRunner().invoke(cli.app, ["ip", p, "--slot", "1"]).output.strip() == "192.0.2.1"
    status = json.loads(CliRunner().invoke(cli.app, ["status", p, "--json"]).output)
    assert [s["name"] for s in status] == ["lab-1"]
    plan = json.loads(CliRunner().invoke(cli.app, ["plan", p, "--json"]).output)
    assert [s["action"] for s in plan["steps"]] == ["keep", "create"]


def test_exit_codes(spec_file, provider, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    p = str(spec_file(2))
    monkeypatch.setattr(guard.os, "geteuid", lambda: 1000)
    r = CliRunner().invoke(cli.app, ["apply", p])
    assert r.exit_code == 3 and "needs sudo" in r.output
    assert CliRunner().invoke(cli.app, ["rebuild", p, "--slot", "7"]).exit_code == 2
    r = CliRunner().invoke(cli.app, ["destroy", p])
    assert r.exit_code == 2 and "--yes" in r.output
    assert CliRunner().invoke(cli.app, ["destroy", p, "--yes"]).exit_code == 0
    assert provider.calls == [("destroy", "lab-1")]
    bad = spec_file(2)
    bad.write_text(bad.read_text().replace("cx22", ""))
    assert CliRunner().invoke(cli.app, ["validate", str(bad)]).exit_code == 2
