# CLAUDE.md — delve

## What this repo is

`delve` provisions virtual machines from a YAML spec (`kind: servers`): plan, apply, rebuild, destroy, status, ip.
Layer 0 of the 1ops family: delve creates the server, loft-cli hardens it. Open source, Apache-2.0.

## Invariants

- **Whatever buys needs sudo** (`guard.require_sudo`): `apply` when it creates. Never add a way around it (no flag,
  no environment variable). Rebuild and destroy buy nothing.
- **No state file.** The provider is the state: Hetzner labels (`managed-by=delve`, `delve-spec`, `delve-slot`),
  OVH exact names in the region. Never delete or rebuild a server delve did not create.
- **Credentials only from the environment**, never in a spec, a log or an exception message.
- **Providers are adapters** with the interface in `providers/base.py`; their SDK client can be passed in, so tests
  use stand-ins. A new provider is a new module and an entry in `provider_for`; nothing in `core` knows a provider.
- **`core` holds the logic, `cli` only adapts** (parse, call core, print, exit code). `--json` prints one line.
- **Tests never call a real provider** and never buy. A real run is the user's decision, with sudo.

## Layout

```
src/delve/
  spec.py        the spec (pydantic), ${env:NAME}, public keys
  model.py       Server, Plan, Step
  core.py        plan, apply, rebuild, destroy, status, select, user_data
  guard.py       sudo for purchases
  ssh.py         wait until root logs in; forget old host keys
  cli.py         Typer commands
  providers/     base.py (interface), hetzner.py (hcloud), ovh.py (ovh)
examples/        specs; `make examples` validates them
tests/           pytest; providers as recording stand-ins
```

## Checks

`make check` (ruff check + format, pyright, pytest, examples). With `RESULTS_DIR` each check writes
`<aspect>.<language>.<format>` and `.exit` for `test-everything results import`.

## Language

Code, comments, commits and docs in English.
