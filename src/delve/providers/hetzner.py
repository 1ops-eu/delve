"""Hetzner Cloud through the official SDK (``hcloud``, extra ``[hetzner]``). The token comes from ``HCLOUD_TOKEN``.

The servers of a spec carry the labels ``managed-by=delve``, ``delve-spec=<meta.name>`` and ``delve-slot=<n>``;
that is how delve finds them again, and it never touches a server without them. Public keys are registered as
SSH keys of the project (reused when the same key is there already), so no root password is mailed, and installed
again through user data on a rebuild, since Hetzner does not re-inject project keys then.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from .. import __version__
from ..model import Server
from ..spec import Spec
from .base import ProviderError


@contextmanager
def _errors(what: str) -> Iterator[None]:
    try:
        yield
    except ProviderError:
        raise
    except Exception as e:  # noqa: BLE001 - every SDK and network error, named as the provider's
        raise ProviderError(f"hetzner: {what}: {e}") from e


class Hetzner:
    name = "hetzner"

    def __init__(self, spec: Spec, client: Any = None) -> None:
        if client is None:
            token = os.environ.get("HCLOUD_TOKEN")
            if not token:
                raise ProviderError("hetzner: HCLOUD_TOKEN is not set")
            try:
                from hcloud import Client
            except ImportError as e:
                raise ProviderError("hetzner: pip install 'delve[hetzner]'") from e
            client = Client(token=token, application_name="delve", application_version=__version__)
        self.client = client
        self.spec = spec

    def _labels(self, slot: int) -> dict[str, str]:
        return {
            **self.spec.servers.labels,
            "managed-by": "delve",
            "delve-spec": self.spec.meta.name,
            "delve-slot": str(slot),
        }

    @staticmethod
    def _server(b: Any) -> Server:
        net = getattr(b, "public_net", None)
        v4 = getattr(getattr(net, "ipv4", None), "ip", None)
        v6 = getattr(getattr(net, "ipv6", None), "ip", None)
        return Server(
            name=b.name,
            slot=int((b.labels or {}).get("delve-slot", "0")),
            id=str(b.id),
            status=str(b.status),
            ipv4=v4,
            ipv6=v6,
        )

    def servers(self) -> list[Server]:
        with _errors("listing servers"):
            found = self.client.servers.get_all(label_selector=f"managed-by=delve,delve-spec={self.spec.meta.name}")
        return sorted((self._server(b) for b in found), key=lambda s: (s.slot, s.name))

    def _keys(self, public_keys: list[str]) -> list[Any]:
        with _errors("ssh keys"):
            known = {k.public_key.strip(): k for k in self.client.ssh_keys.get_all()}
            out = []
            for i, pk in enumerate(public_keys, start=1):
                key = known.get(pk.strip())
                if key is None:
                    key = self.client.ssh_keys.create(
                        name=f"delve-{self.spec.meta.name}-{i}",
                        public_key=pk,
                        labels={"managed-by": "delve", "delve-spec": self.spec.meta.name},
                    )
                out.append(key)
            return out

    def create(self, name: str, slot: int, public_keys: list[str], user_data: str) -> Server:
        from hcloud.images.domain import Image
        from hcloud.locations.domain import Location
        from hcloud.server_types.domain import ServerType

        s = self.spec.servers
        keys = self._keys(public_keys)
        with _errors(f"creating {name}"):
            r = self.client.servers.create(
                name=name,
                server_type=ServerType(name=s.type),
                image=Image(name=s.image),
                location=Location(name=s.location),
                ssh_keys=keys,
                labels=self._labels(slot),
                user_data=user_data,
            )
            r.action.wait_until_finished()
            for a in r.next_actions or []:
                a.wait_until_finished()
            return self._server(self.client.servers.get_by_id(r.server.id))

    def rebuild(self, server: Server, public_keys: list[str], user_data: str) -> Server:
        from hcloud.images.domain import Image

        with _errors(f"rebuilding {server.name}"):
            bound = self.client.servers.get_by_id(int(server.id))
            r = self.client.servers.rebuild(bound, Image(name=self.spec.servers.image), user_data=user_data)
            r.action.wait_until_finished()
            return self._server(self.client.servers.get_by_id(int(server.id)))

    def destroy(self, server: Server) -> None:
        with _errors(f"deleting {server.name}"):
            bound = self.client.servers.get_by_id(int(server.id))
            if (bound.labels or {}).get("managed-by") != "delve":
                raise ProviderError(f"hetzner: {server.name} is not managed by delve; not deleting it")
            self.client.servers.delete(bound).wait_until_finished()
