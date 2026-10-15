"""OVHcloud Public Cloud through the official client (``ovh``, extra ``[ovh]``). Credentials come from the
environment the client reads itself (``OVH_ENDPOINT``, ``OVH_APPLICATION_KEY``, ``OVH_APPLICATION_SECRET``,
``OVH_CONSUMER_KEY``); the project from ``provider.project`` or ``OVH_CLOUD_PROJECT``.

Instances carry no labels at OVH, so delve finds the servers of a spec by their exact names in the spec's region,
and touches nothing else. Flavor and image are looked up by name in that region. The first public key becomes the
instance's SSH key (registered once, reused by its key); every key is also installed through user data on create.
A reinstall keeps the instance's SSH key; OVH takes no user data there.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from ..model import Server
from ..spec import Spec
from .base import ProviderError


@contextmanager
def _errors(what: str) -> Iterator[None]:
    try:
        yield
    except ProviderError:
        raise
    except Exception as e:  # noqa: BLE001 - every client and network error, named as the provider's
        raise ProviderError(f"ovh: {what}: {e}") from e


class Ovh:
    name = "ovh"

    def __init__(
        self,
        spec: Spec,
        client: Any = None,
        sleep: Callable[[float], None] = time.sleep,
        timeout_s: float = 900,
    ) -> None:
        project = spec.provider.project or os.environ.get("OVH_CLOUD_PROJECT")
        if not project:
            raise ProviderError("ovh: give provider.project or set OVH_CLOUD_PROJECT")
        if client is None:
            try:
                import ovh
            except ImportError as e:
                raise ProviderError("ovh: pip install 'delve[ovh]'") from e
            with _errors("client"):
                client = ovh.Client()
        self.client = client
        self.spec = spec
        self.base = f"/cloud/project/{project}"
        self.sleep = sleep
        self.timeout_s = timeout_s

    def _slots(self) -> dict[str, int]:
        return {name: slot for slot, name in self.spec.names()}

    def _server(self, inst: dict[str, Any]) -> Server:
        v4 = next(
            (a["ip"] for a in inst.get("ipAddresses") or [] if a.get("version") == 4 and a.get("type") == "public"),
            None,
        )
        v6 = next((a["ip"] for a in inst.get("ipAddresses") or [] if a.get("version") == 6), None)
        return Server(
            name=inst["name"],
            slot=self._slots().get(inst["name"], 0),
            id=str(inst["id"]),
            status=str(inst.get("status")),
            ipv4=v4,
            ipv6=v6,
        )

    def servers(self) -> list[Server]:
        names = self._slots()
        prefix = f"{self.spec.servers.name}-"
        with _errors("listing instances"):
            found = self.client.get(f"{self.base}/instance", region=self.spec.servers.location)
        mine = [
            i
            for i in found
            if i.get("region") == self.spec.servers.location
            and (i["name"] in names or (i["name"].startswith(prefix) and i["name"][len(prefix) :].isdigit()))
        ]
        servers = [self._server(i) for i in mine]
        for s in servers:  # beyond the count: still this spec's, by its name
            if s.slot == 0 and s.name.startswith(prefix):
                s.slot = int(s.name[len(prefix) :])
        return sorted(servers, key=lambda s: (s.slot, s.name))

    def _named(self, path: str, name: str, what: str, **query: Any) -> str:
        with _errors(f"looking up {what} {name}"):
            items = self.client.get(f"{self.base}/{path}", **query)
        hit = next((x for x in items if x.get("name") == name), None)
        if hit is None:
            raise ProviderError(f"ovh: no {what} named {name!r} in {self.spec.servers.location}")
        return str(hit["id"])

    def _key_id(self, public_key: str) -> str:
        region = self.spec.servers.location
        with _errors("ssh keys"):
            for k in self.client.get(f"{self.base}/sshkey", region=region):
                if k.get("publicKey", "").strip() == public_key.strip():
                    return str(k["id"])
            made = self.client.post(
                f"{self.base}/sshkey", name=f"delve-{self.spec.meta.name}", publicKey=public_key, region=region
            )
            return str(made["id"])

    def _wait_active(self, inst_id: str, name: str) -> dict[str, Any]:
        waited = 0.0
        while True:
            with _errors(f"waiting for {name}"):
                inst = self.client.get(f"{self.base}/instance/{inst_id}")
            if inst.get("status") == "ACTIVE":
                return inst
            if inst.get("status") == "ERROR":
                raise ProviderError(f"ovh: {name} went into ERROR")
            if waited >= self.timeout_s:
                raise ProviderError(f"ovh: {name} not ACTIVE after {self.timeout_s:.0f}s")
            self.sleep(10)
            waited += 10

    def create(self, name: str, slot: int, public_keys: list[str], user_data: str) -> Server:
        s = self.spec.servers
        flavor = self._named("flavor", s.type, "flavor", region=s.location)
        image = self._named("image", s.image, "image", region=s.location, osType="linux")
        key = self._key_id(public_keys[0])
        with _errors(f"creating {name}"):
            inst = self.client.post(
                f"{self.base}/instance",
                name=name,
                flavorId=flavor,
                imageId=image,
                region=s.location,
                sshKeyId=key,
                userData=user_data,
                monthlyBilling=False,
            )
        return self._server(self._wait_active(str(inst["id"]), name))

    def rebuild(self, server: Server, public_keys: list[str], user_data: str) -> Server:
        s = self.spec.servers
        image = self._named("image", s.image, "image", region=s.location, osType="linux")
        with _errors(f"reinstalling {server.name}"):
            self.client.post(f"{self.base}/instance/{server.id}/reinstall", imageId=image)
        self.sleep(10)  # the reinstall first leaves ACTIVE
        return self._server(self._wait_active(server.id, server.name))

    def destroy(self, server: Server) -> None:
        if server.name not in self._slots() and not server.name.startswith(f"{self.spec.servers.name}-"):
            raise ProviderError(f"ovh: {server.name} is not a server of this spec; not deleting it")
        with _errors(f"deleting {server.name}"):
            self.client.delete(f"{self.base}/instance/{server.id}")
