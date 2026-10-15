"""The Hetzner and OVH adapters against stand-ins of their clients that record every call: labels and names that
find a spec's servers, keys registered once, waiting, and refusing servers that are not delve's."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace as NS
from typing import Any

import pytest

from delve.model import Server
from delve.providers import ProviderError
from delve.providers.hetzner import Hetzner
from delve.providers.ovh import Ovh
from delve.spec import load


class _Action:
    def __init__(self, log: list[str], what: str) -> None:
        self.log, self.what = log, what

    def wait_until_finished(self, max_retries: int | None = None) -> None:
        self.log.append(f"wait {self.what}")


def _bound(name: str, slot: int, sid: int, managed: bool = True) -> NS:
    labels = {"managed-by": "delve", "delve-spec": "lab", "delve-slot": str(slot)} if managed else {}
    return NS(name=name, id=sid, status="running", labels=labels,
              public_net=NS(ipv4=NS(ip=f"192.0.2.{slot}"), ipv6=NS(ip="2001:db8::/64")))  # fmt: skip


class FakeHcloud:
    def __init__(self, known_keys: list[str] | None = None) -> None:
        self.log: list[str] = []
        self.by_id = {11: _bound("lab-1", 1, 11)}
        keys = [NS(public_key=k, name=f"k{i}") for i, k in enumerate(known_keys or [])]
        outer = self

        class Servers:
            def get_all(self, label_selector: str) -> list[NS]:
                outer.log.append(f"get_all {label_selector}")
                return [b for b in outer.by_id.values() if b.labels.get("delve-spec") == "lab"]

            def get_by_id(self, sid: int) -> NS:
                return outer.by_id[sid]

            def create(self, **kw: Any) -> NS:
                parts = (kw["name"], kw["server_type"].name, kw["image"].name, kw["location"].name)
                outer.log.append("create " + " ".join(parts))
                outer.created = kw
                b = _bound(kw["name"], int(kw["labels"]["delve-slot"]), 12)
                outer.by_id[12] = b
                return NS(action=_Action(outer.log, "create"), next_actions=[_Action(outer.log, "start")], server=b)

            def rebuild(self, b: NS, image: Any, user_data: str) -> NS:
                outer.log.append(f"rebuild {b.name} {image.name}")
                return NS(action=_Action(outer.log, "rebuild"))

            def delete(self, b: NS) -> _Action:
                outer.log.append(f"delete {b.name}")
                return _Action(outer.log, "delete")

        class Keys:
            def get_all(self) -> list[NS]:
                return keys

            def create(self, name: str, public_key: str, labels: dict[str, str]) -> NS:
                outer.log.append(f"key {name}")
                return NS(name=name, public_key=public_key)

        self.servers, self.ssh_keys = Servers(), Keys()


def _spec(tmp_path: Path, provider: str, extra: str = "") -> Any:
    (tmp_path / "ops.pub").write_text("ssh-ed25519 AAA ops\n")
    p = tmp_path / "s.yaml"
    p.write_text(
        f"kind: servers\nmeta: {{name: lab}}\nprovider: {{name: {provider}{extra}}}\n"
        "servers: {name: lab, count: 2, type: cx22, image: ubuntu-24.04, location: fsn1, ssh_keys: [ops.pub]}\n"
    )
    return load(p, environ={})


def test_hetzner_finds_creates_rebuilds_and_deletes(tmp_path: Path) -> None:
    c = FakeHcloud()
    h = Hetzner(_spec(tmp_path, "hetzner"), client=c)
    assert [(s.name, s.slot, s.ipv4) for s in h.servers()] == [("lab-1", 1, "192.0.2.1")]
    assert c.log[0] == "get_all managed-by=delve,delve-spec=lab"
    made = h.create("lab-2", 2, ["ssh-ed25519 AAA ops"], "#!/bin/bash\n")
    assert made.ipv4 == "192.0.2.2"
    assert c.created["labels"] == {"managed-by": "delve", "delve-spec": "lab", "delve-slot": "2"}
    assert c.log[1:] == ["key delve-lab-1", "create lab-2 cx22 ubuntu-24.04 fsn1", "wait create", "wait start"]
    h.rebuild(made, ["ssh-ed25519 AAA ops"], "#!/bin/bash\n")
    h.destroy(made)
    assert c.log[-4:] == ["rebuild lab-2 ubuntu-24.04", "wait rebuild", "delete lab-2", "wait delete"]


def test_hetzner_reuses_a_known_key_and_spares_foreign_servers(tmp_path: Path) -> None:
    c = FakeHcloud(known_keys=["ssh-ed25519 AAA ops"])
    h = Hetzner(_spec(tmp_path, "hetzner"), client=c)
    h.create("lab-2", 2, ["ssh-ed25519 AAA ops"], "")
    assert not [x for x in c.log if x.startswith("key ")]
    c.by_id[99] = _bound("someone-else", 1, 99, managed=False)
    with pytest.raises(ProviderError, match="not managed by delve"):
        h.destroy(Server(name="someone-else", slot=1, id="99", status="running", ipv4=None))


def test_hetzner_needs_a_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HCLOUD_TOKEN", raising=False)
    with pytest.raises(ProviderError, match="HCLOUD_TOKEN is not set"):
        Hetzner(_spec(tmp_path, "hetzner"))


class FakeOvh:
    def __init__(self) -> None:
        self.log: list[str] = []
        self.instances = {
            "i1": {"id": "i1", "name": "lab-1", "region": "fsn1", "status": "ACTIVE",
                   "ipAddresses": [{"ip": "198.51.100.1", "version": 4, "type": "public"}]},
            "i9": {"id": "i9", "name": "other", "region": "fsn1", "status": "ACTIVE", "ipAddresses": []},
        }  # fmt: skip
        self.polls = 0

    def get(self, path: str, **q: Any) -> Any:
        self.log.append(f"GET {path} {sorted(q.items())}")
        if path.endswith("/instance"):
            return list(self.instances.values())
        if "/instance/" in path:
            self.polls += 1
            inst = self.instances[path.rsplit("/", 1)[1]]
            return {**inst, "status": "BUILD" if self.polls == 1 else "ACTIVE"}
        if path.endswith("/flavor"):
            return [{"id": "f-cx22", "name": "cx22"}]
        if path.endswith("/image"):
            return [{"id": "img-1", "name": "ubuntu-24.04"}]
        if path.endswith("/sshkey"):
            return []
        raise AssertionError(path)

    def post(self, path: str, **body: Any) -> Any:
        self.log.append(f"POST {path} {sorted(body)}")
        if path.endswith("/sshkey"):
            return {"id": "k1"}
        if path.endswith("/instance"):
            self.body = body
            inst = {"id": "i2", "name": body["name"], "region": body["region"], "status": "BUILD",
                    "ipAddresses": [{"ip": "198.51.100.2", "version": 4, "type": "public"}]}  # fmt: skip
            self.instances["i2"] = inst
            return inst
        return None

    def delete(self, path: str) -> None:
        self.log.append(f"DELETE {path}")


def test_ovh_finds_by_name_creates_waits_and_deletes(tmp_path: Path) -> None:
    c = FakeOvh()
    o = Ovh(_spec(tmp_path, "ovh", ", project: p1"), client=c, sleep=lambda s: None)
    assert [(s.name, s.slot, s.ipv4) for s in o.servers()] == [("lab-1", 1, "198.51.100.1")]  # "other" is not ours
    made = o.create("lab-2", 2, ["ssh-ed25519 AAA ops"], "#!/bin/bash\n")
    assert (made.name, made.ipv4, made.status) == ("lab-2", "198.51.100.2", "ACTIVE")
    assert c.body["flavorId"] == "f-cx22" and c.body["imageId"] == "img-1" and c.body["sshKeyId"] == "k1"
    assert c.body["monthlyBilling"] is False
    o.rebuild(made, ["ssh-ed25519 AAA ops"], "")
    o.destroy(made)
    assert "POST /cloud/project/p1/instance/i2/reinstall ['imageId']" in c.log
    assert c.log[-1] == "DELETE /cloud/project/p1/instance/i2"
    with pytest.raises(ProviderError, match="not a server of this spec"):
        o.destroy(Server(name="other", slot=0, id="i9", status="ACTIVE", ipv4=None))


def test_ovh_needs_a_project_and_names_what_it_cannot_find(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OVH_CLOUD_PROJECT", raising=False)
    with pytest.raises(ProviderError, match="provider.project"):
        Ovh(_spec(tmp_path, "ovh"), client=FakeOvh())
    c = FakeOvh()
    o = Ovh(_spec(tmp_path, "ovh", ", project: p1"), client=c, sleep=lambda s: None)
    o.spec.servers.type = "b9-999"
    with pytest.raises(ProviderError, match="no flavor named 'b9-999'"):
        o.create("lab-2", 2, ["ssh-ed25519 AAA ops"], "")
