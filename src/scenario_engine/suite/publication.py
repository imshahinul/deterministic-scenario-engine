"""Atomic publication for canonical suite artifacts."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile


def publish_suite_bytes(data: bytes, destination: str | os.PathLike[str]) -> None:
    """Atomically publish bytes to an absent path in an existing directory."""
    if not isinstance(data, bytes):
        raise TypeError("suite artifact data must be bytes")
    target = Path(destination)
    parent = target.parent
    if not parent.is_dir():
        raise FileNotFoundError("suite artifact parent directory does not exist")
    temporary_name: str | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(prefix=".scenario-replay-", dir=parent)
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary_name, target)
        os.unlink(temporary_name)
        temporary_name = None
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
