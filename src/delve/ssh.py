"""Waiting until a fresh server answers on SSH, the way the old pool scripts did: the port first, then a login."""

from __future__ import annotations

import contextlib
import socket
import subprocess
import time
from collections.abc import Callable


class SshTimeout(TimeoutError):
    pass


def forget_host(address: str) -> None:
    """A rebuilt server has new host keys; drop the old ones from known_hosts."""
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(["ssh-keygen", "-R", address], capture_output=True, text=True, timeout=10)


def wait_for_ssh(
    host: str,
    *,
    port: int = 22,
    user: str = "root",
    key: str | None = None,
    timeout_s: float = 300,
    interval_s: float = 5,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    start = clock()
    while clock() - start < timeout_s:
        try:
            socket.create_connection((host, port), timeout=5).close()
        except OSError:
            sleep(interval_s)
            continue
        cmd = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR",
               "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", "-p", str(port)]  # fmt: skip
        if key:
            cmd += ["-i", key]
        try:
            r = subprocess.run(
                [*cmd, f"{user}@{host}", "echo", "SSH_READY"], capture_output=True, text=True, timeout=15
            )
            if r.returncode == 0 and "SSH_READY" in r.stdout:
                return
        except subprocess.TimeoutExpired:
            pass
        sleep(interval_s)
    raise SshTimeout(f"SSH on {host}:{port} not ready within {timeout_s:.0f}s")
