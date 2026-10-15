"""The spec: which servers a provider should run for one name. One YAML document, ``kind: servers``.

Values may name environment variables as ``${env:NAME}`` (as in loft-cli); a missing one is an error, never an
empty string. Credentials never stand in a spec: providers read them from the environment.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

NAME = r"^[a-z0-9][a-z0-9-]{0,40}$"
ENV_REF = re.compile(r"\$\{env:([A-Za-z_][A-Za-z0-9_]*)\}")


class SpecError(ValueError):
    """The spec cannot be read or is not valid; the message says why."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Meta(_Model):
    name: str = Field(pattern=NAME)  # identifies the servers of this spec at the provider
    description: str = ""


class Provider(_Model):
    name: Literal["hetzner", "ovh"]
    project: str | None = None  # OVH: the Public Cloud project (service name); else OVH_CLOUD_PROJECT


class Servers(_Model):
    name: str = Field(pattern=NAME)  # a pool of count > 1 is named <name>-<slot>
    count: int = Field(default=1, ge=1, le=50)
    type: str = Field(min_length=1)  # Hetzner server type (cx22) or OVH flavor (b3-8)
    image: str = Field(min_length=1)  # Hetzner image (ubuntu-24.04) or OVH image name (Ubuntu 24.04)
    location: str = Field(min_length=1)  # Hetzner location (fsn1) or OVH region (GRA11)
    ssh_keys: list[str] = Field(min_length=1)  # public key files; installed for root on create and rebuild
    labels: dict[str, str] = {}

    @field_validator("ssh_keys")
    @classmethod
    def _public_keys(cls, files: list[str]) -> list[str]:
        for f in files:
            if not f.endswith(".pub"):
                raise ValueError(f"{f}: give public key files (.pub), never a private key")
        return files


class Spec(_Model):
    kind: Literal["servers"]
    meta: Meta
    provider: Provider
    servers: Servers

    def names(self) -> list[tuple[int, str]]:
        """Every server of the spec: (slot, name)."""
        s = self.servers
        if s.count == 1:
            return [(1, s.name)]
        return [(i, f"{s.name}-{i}") for i in range(1, s.count + 1)]

    def public_keys(self, base: Path) -> list[str]:
        keys = []
        for f in self.servers.ssh_keys:
            p = Path(f).expanduser()
            p = p if p.is_absolute() else base / p
            if not p.is_file():
                raise SpecError(f"ssh key {f}: no file {p}")
            keys.append(p.read_text(encoding="utf-8").strip())
        return keys


def _resolve(value: Any, env: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {k: _resolve(v, env) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v, env) for v in value]
    if isinstance(value, str):

        def sub(m: re.Match[str]) -> str:
            if m.group(1) not in env:
                raise SpecError(f"${{env:{m.group(1)}}} is not set")
            return env[m.group(1)]

        return ENV_REF.sub(sub, value)
    return value


def load(path: Path, environ: dict[str, str] | None = None) -> Spec:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        raise SpecError(f"{path}: {e}") from None
    if not isinstance(raw, dict):
        raise SpecError(f"{path}: a spec is one YAML mapping")
    try:
        return Spec.model_validate(_resolve(raw, dict(os.environ if environ is None else environ)))
    except ValidationError as e:
        problems = "; ".join(f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors())
        raise SpecError(f"{path}: {problems}") from None
