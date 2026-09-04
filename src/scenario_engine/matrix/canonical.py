"""Typed canonical identities for matrix plans and cases."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from scenario_engine.values import normalize

from .errors import MatrixDeclarationError


MATRIX_PLAN_CONTRACT_VERSION = "matrix.plan/1"


def canonical_matrix_bytes(value: Any) -> bytes:
    """Encode a semantic matrix envelope without repr or host coordinates."""
    try:
        normalized = normalize(value)
        return json.dumps(
            normalized, ensure_ascii=False, allow_nan=False, sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise MatrixDeclarationError("matrix contains an invalid semantic value") from None


def matrix_plan_hash(
    suite_hash: str,
    dimensions: Sequence[Any],
    filters: Sequence[Mapping[str, Any]],
) -> str:
    envelope = {
        "contract_version": MATRIX_PLAN_CONTRACT_VERSION,
        "dimensions": [
            {"name": item.name, "values": list(item.values)} for item in dimensions
        ],
        "filters": list(filters),
        "suite_hash": suite_hash,
    }
    return hashlib.sha256(canonical_matrix_bytes(envelope)).hexdigest()


def stable_case_id(
    suite_hash: str,
    case_index: int,
    assignment: Mapping[str, Any],
) -> str:
    """Hash the frozen version, suite identity, raw index, and ordered coordinates."""
    envelope = {
        "assignment": [[name, assignment[name]] for name in assignment],
        "case_index": case_index,
        "contract_version": "matrix.case/1",
        "suite_hash": suite_hash,
    }
    return hashlib.sha256(canonical_matrix_bytes(envelope)).hexdigest()
