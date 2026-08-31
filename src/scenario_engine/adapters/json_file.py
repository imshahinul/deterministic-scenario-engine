"""Atomic filesystem output for canonical :class:`ScenarioResult` JSON bytes."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
from typing import Final

from scenario_engine.result import ScenarioResult


_TEMP_PREFIX: Final = ".scenario-result-"


def write_result_json(
    result: ScenarioResult,
    path: str | os.PathLike[str],
    *,
    overwrite: bool = False,
) -> None:
    """Write canonical result bytes using guarded, same-directory replacement.

    This is process-level guarded atomic replacement, not a distributed
    transaction. The caller must provide an existing parent directory.
    """
    if not isinstance(result, ScenarioResult):
        raise TypeError("result must be a ScenarioResult")

    target = Path(path)
    parent = target.parent
    if not parent.is_dir():
        raise FileNotFoundError(f"target parent directory does not exist: {parent}")
    if not overwrite and target.exists():
        raise FileExistsError(target)

    temporary_name: str | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(prefix=_TEMP_PREFIX, dir=parent)
        with os.fdopen(descriptor, "wb") as output:
            output.write(result.to_json_bytes())
            output.flush()
            os.fsync(output.fileno())

        if overwrite:
            os.replace(temporary_name, target)
        else:
            # Hard-link publication is atomic and refuses an existing target,
            # including one created after the process-level preflight check.
            os.link(temporary_name, target)
            os.unlink(temporary_name)
        temporary_name = None
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
