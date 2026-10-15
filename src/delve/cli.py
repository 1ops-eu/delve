"""The delve command line: parse, call ``core``, print. ``--json`` prints one line (an object with ``--slot``,
else a list), so other tools read it directly: a testbed action of test-everything reads ``{"host": …}``.

Exit codes: 0 done · 1 the provider failed · 2 the spec or the selection is wrong · 3 a purchase without sudo.

Semantics: capability=delve
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, NoReturn

import typer

from . import __version__, core
from .guard import PurchaseRefused
from .providers import ProviderError, provider_for
from .spec import Spec, SpecError, load
from .ssh import SshTimeout

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Provision virtual machines from a YAML spec.")

SPEC = typer.Argument(..., exists=True, dir_okay=False, help="the spec (kind: servers)")
JSON = typer.Option(False, "--json", help="one line of JSON")
SLOT = typer.Option(None, "--slot", min=1, help="only this slot of a pool")


def _fail(code: int, message: str) -> NoReturn:
    typer.echo(f"ERROR {message}", err=True)
    raise typer.Exit(code)


def _spec(path: Path) -> Spec:
    try:
        return load(path)
    except SpecError as e:
        _fail(2, str(e))


def _run(fn: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return fn(*args, **kwargs)
    except SpecError as e:
        _fail(2, str(e))
    except core.SelectionError as e:
        _fail(2, str(e))
    except PurchaseRefused as e:
        _fail(3, str(e))
    except (ProviderError, SshTimeout) as e:
        _fail(1, str(e))


def _emit(as_json: bool, data: Any, text: str) -> None:
    typer.echo(json.dumps(data, separators=(",", ":"), default=str) if as_json else text)


def _servers_text(servers: list[Any]) -> str:
    return "\n".join(f"{s.slot:>3}  {s.name:<32} {s.status:<12} {s.ipv4 or '-'}" for s in servers) or "(none)"


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(__version__)


@app.command()
def validate(spec: Path = SPEC) -> None:
    """Check a spec without asking any provider."""
    s = _spec(spec)
    _run(s.public_keys, spec.parent)
    typer.echo(f"{spec}: valid ({s.provider.name}, {s.servers.count} server(s))")


@app.command()
def plan(spec: Path = SPEC, as_json: bool = JSON) -> None:
    """What apply would do: create, keep, and servers beyond the count."""
    s = _spec(spec)
    p = _run(core.plan, s, _run(provider_for, s))
    text = "\n".join(f"{st.action:<8} {st.name}" for st in p.steps)
    _emit(as_json, p.to_dict(), text)


@app.command()
def apply(spec: Path = SPEC, as_json: bool = JSON) -> None:
    """Create every server of the spec the provider does not have yet (sudo: it buys resources)."""
    s = _spec(spec)
    p = _run(core.apply, s, _run(provider_for, s), spec.parent)
    _emit(as_json, p.to_dict(), "\n".join(f"{st.action:<8} {st.name} {(st.server.ipv4 if st.server else '') or ''}"
                                          for st in p.steps))  # fmt: skip


@app.command()
def rebuild(
    spec: Path = SPEC,
    slot: int | None = SLOT,
    wait_ssh: bool = typer.Option(False, "--wait-ssh", help="wait until root logs in over SSH"),
    ssh_key: str | None = typer.Option(None, "--ssh-key", help="private key for the SSH check"),
    ssh_timeout: float = typer.Option(300, "--ssh-timeout", help="seconds"),
    as_json: bool = JSON,
) -> None:
    """Install the image anew on the spec's servers (same addresses, fresh disk)."""
    s = _spec(spec)
    done = _run(core.rebuild, s, _run(provider_for, s), spec.parent, slot, wait_ssh, ssh_key, ssh_timeout)
    data = done[0].to_dict() if slot is not None else [x.to_dict() for x in done]
    _emit(as_json, data, _servers_text(done))


@app.command()
def destroy(
    spec: Path = SPEC,
    slot: int | None = SLOT,
    yes: bool = typer.Option(False, "--yes", help="really delete"),
    as_json: bool = JSON,
) -> None:
    """Delete the spec's servers (or one slot). Asks for --yes."""
    if not yes:
        _fail(2, "destroy deletes servers and everything on them; add --yes")
    s = _spec(spec)
    gone = _run(core.destroy, s, _run(provider_for, s), slot)
    _emit(as_json, [x.to_dict() for x in gone], _servers_text(gone))


@app.command()
def status(spec: Path = SPEC, as_json: bool = JSON) -> None:
    """The spec's servers at the provider."""
    s = _spec(spec)
    servers = _run(core.status, _run(provider_for, s))
    _emit(as_json, [x.to_dict() for x in servers], _servers_text(servers))


@app.command()
def ip(spec: Path = SPEC, slot: int | None = SLOT, as_json: bool = JSON) -> None:
    """The public IPv4 address of the spec's servers (or one slot)."""
    s = _spec(spec)
    chosen = _run(core.select, s, _run(core.status, _run(provider_for, s)), slot)
    data = {"name": chosen[0].name, "slot": chosen[0].slot, "host": chosen[0].ipv4} if slot is not None else [
        {"name": x.name, "slot": x.slot, "host": x.ipv4} for x in chosen]  # fmt: skip
    _emit(as_json, data, "\n".join(x.ipv4 or "-" for x in chosen))


if __name__ == "__main__":  # pragma: no cover
    app()
