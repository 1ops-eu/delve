# delve

Provision virtual machines from a YAML spec — **delve in before you loft-cli up.** delve creates, rebuilds and
deletes servers at a cloud provider; [loft-cli](https://github.com/1ops-eu/loft-cli) then hardens and configures
them. Providers: **Hetzner Cloud** and **OVHcloud Public Cloud**.

```bash
pip install 'delve[all]'            # or [hetzner] / [ovh]
delve validate web.yaml             # the spec alone, no provider asked
delve plan web.yaml                 # create / keep / surplus
sudo -E delve apply web.yaml        # create what is missing (buys servers: sudo on purpose)
delve status web.yaml
delve ip web.yaml
delve rebuild web.yaml --wait-ssh   # fresh disk, same address
delve destroy web.yaml --yes
```

## The spec

```yaml
kind: servers
meta:
  name: lab                      # identifies these servers at the provider
  description: e2e test pool
provider:
  name: hetzner                  # hetzner | ovh
  # project: ${env:OVH_CLOUD_PROJECT}   (ovh: the Public Cloud project)
servers:
  name: lab
  count: 3                       # a pool: lab-1, lab-2, lab-3 (count 1: just "lab")
  type: cx22                     # Hetzner server type, or OVH flavor (b3-8)
  image: ubuntu-24.04            # Hetzner image, or OVH image name (Ubuntu 24.04)
  location: nbg1                 # Hetzner location, or OVH region (GRA11)
  ssh_keys: [~/.ssh/id_ed25519.pub]   # public key files only; installed for root
  labels: {team: ops}
```

`${env:NAME}` takes a value from the environment (as in loft-cli); an unset one is an error. Examples:
`examples/`.

## Commands

| Command | Does | Needs |
|---|---|---|
| `validate SPEC` | checks the spec and that its key files exist | – |
| `plan SPEC` | `create` (missing), `keep` (there), `surplus` (beyond the count) | credentials |
| `apply SPEC` | creates every missing server and waits until it runs | **sudo** (it buys) |
| `rebuild SPEC [--slot N] [--wait-ssh]` | installs the image anew: fresh disk, same address, keys installed again | – |
| `destroy SPEC [--slot N] --yes` | deletes the spec's servers (also those beyond the count) | `--yes` |
| `status SPEC`, `ip SPEC [--slot N]` | what runs and where | – |

`--json` prints one line: an object with `--slot`, else a list. Exit codes: 0 done, 1 the provider failed, 2 the
spec or the selection is wrong, 3 a purchase without sudo.

**Why sudo for apply.** Creating servers costs money. Whatever buys runs only under sudo, so an agent or a pipeline
cannot buy unattended: the password prompt is the human in the loop. `sudo -E` keeps the credentials. Rebuilding and
deleting buy nothing and need no sudo.

**No state file.** The provider is the state. At Hetzner the servers carry the labels `managed-by=delve`,
`delve-spec=<meta.name>` and `delve-slot=<n>`; at OVH (no labels) delve finds them by their exact names in the
spec's region. delve never deletes a server it did not create.

## Providers

| Provider | Credentials (environment only) | Notes |
|---|---|---|
| Hetzner Cloud | `HCLOUD_TOKEN` | public keys become project SSH keys (no root password mail) and are installed again on rebuild via user data |
| OVHcloud Public Cloud | `OVH_ENDPOINT`, `OVH_APPLICATION_KEY`, `OVH_APPLICATION_SECRET`, `OVH_CONSUMER_KEY`; project via `provider.project` or `OVH_CLOUD_PROJECT` | flavor and image by name in the region; hourly billing; a reinstall keeps the instance's SSH key |

A provider is an adapter with five operations (`servers`, `create`, `rebuild`, `destroy`; `src/delve/providers/`).

## With other tools

- **loft-cli:** `delve ip SPEC --slot 1` gives the address for the loft-cli spec's `host.address`.
- **test-everything:** a `command` testbed resets a pool slot and publishes its address:

  ```yaml
  name: pool
  driver: command
  settings:
    user: root
    key: secret:pool_ssh_key
    env: {HCLOUD_TOKEN: "secret:hcloud_token"}
    actions:
      reset: "delve rebuild lab.yaml --slot 1 --wait-ssh --ssh-key ~/.ssh/pool_ed25519 --json"
  ```

## Development

```bash
make dev          # .venv with both providers and the tools
make check        # ruff, pyright, pytest, every example validated
make test RESULTS_DIR=.results   # results for test-everything results import
```

The tests need no cloud account: the providers' clients are replaced by stand-ins that record every call. Nothing in
the test suite buys anything.

License: Apache-2.0.
