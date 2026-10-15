"""The guard against unintended cost: whatever buys paid resources runs only under sudo. The password prompt is
the human in the loop an agent or a pipeline cannot skip. Deleting and reinstalling buy nothing and need no sudo."""

from __future__ import annotations

import os
from collections.abc import Callable


class PurchaseRefused(PermissionError):
    """A purchase was asked for without sudo."""


def require_sudo(what: str, geteuid: Callable[[], int] | None = None) -> None:
    if (geteuid or os.geteuid)() != 0:
        raise PurchaseRefused(
            f"{what} buys paid cloud resources and needs sudo: sudo -E delve ... "
            "(-E keeps the provider's credentials; the password prompt is the intended human in the loop)"
        )
