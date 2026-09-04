"""Matrix orchestration over the frozen v1 and Phase 2.2 runtimes."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from scenario_engine.composition import ComposedSuite, execute_composed_suite
from scenario_engine.dsl import CompiledScenario, run_scenario
from scenario_engine.plugins import PluginRegistry
from scenario_engine.suite import (
    ArtifactReference, BoundsMetadata, ExecutionContext, MatrixCase,
    MatrixCaseResultEnvelope, MatrixManifest, MatrixResultEnvelope,
    canonical_suite_bytes,
)

from .errors import MatrixCaseIdentityError, UnsupportedParameterBindingError
from .expand import expand_matrix, raw_cardinality, select_matrix_case
from .models import MAX_RAW_CARDINALITY, MatrixExecution, MatrixPlan


def _inputs(case: MatrixCase, inputs: Mapping[str, Any] | None) -> dict[str, Any]:
    result = dict(inputs or {})
    collision = set(result) & set(case.assignment)
    if collision:
        raise UnsupportedParameterBindingError(
            "matrix parameter conflicts with explicit input: " + ",".join(sorted(collision))
        )
    result.update(case.assignment)
    return result


def execute_matrix_case(
    plan: MatrixPlan,
    case: MatrixCase | str,
    *,
    inputs: Mapping[str, Any] | None = None,
    plugins: PluginRegistry | None = None,
):
    """Execute exactly one retained case at its original Cartesian run index."""
    selected = select_matrix_case(plan, case) if isinstance(case, str) else case
    if not isinstance(selected, MatrixCase):
        raise TypeError("case must be a MatrixCase or case ID")
    expected = select_matrix_case(plan, selected.case_id)
    if expected != selected:
        raise MatrixCaseIdentityError("matrix case does not match its plan")
    if plan.target is None:
        raise MatrixCaseIdentityError("matrix plan has no executable target")
    bound_inputs = _inputs(selected, inputs)
    if isinstance(plan.target, ComposedSuite):
        return execute_composed_suite(
            plan.target, plan.root_seed, run_index=selected.case_index,
            locale=plan.locale, inputs=bound_inputs, plugins=plugins,
        ).result
    if isinstance(plan.target, CompiledScenario):
        return run_scenario(
            plan.target, plan.root_seed, run_index=selected.case_index,
            locale=plan.locale, inputs=bound_inputs, plugins=plugins,
        )
    raise MatrixCaseIdentityError("matrix plan target is unsupported")


def execute_matrix(
    plan: MatrixPlan,
    *,
    inputs: Mapping[str, Any] | None = None,
    plugins: PluginRegistry | None = None,
) -> MatrixExecution:
    """Execute retained cases serially and preserve original-index result order."""
    cases = expand_matrix(plan)
    results = tuple(execute_matrix_case(plan, case, inputs=inputs, plugins=plugins) for case in cases)
    case_envelopes = []
    result_references = []
    for case, result in zip(cases, results):
        manifest_bytes = json.dumps(
            result.manifest.normalized(), ensure_ascii=False, sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        result_hash = hashlib.sha256(result.to_json_bytes()).hexdigest()
        manifest_ref = ArtifactReference("run_manifest", case.case_id, manifest_hash)
        result_ref = ArtifactReference("scenario_result", case.case_id, result_hash)
        case_envelopes.append(MatrixCaseResultEnvelope(case, manifest_ref, result_ref))
        result_references.append(result_ref)
    target = plan.target
    reference_clock = target.compiled.reference_clock_start if isinstance(target, ComposedSuite) else target.reference_clock_start
    context = ExecutionContext(plan.root_seed, 0, plan.locale, reference_clock)
    manifest = MatrixManifest(
        suite_identity=plan.suite_identity,
        suite_hash=plan.plan_id,
        execution_context=context,
        bounds=BoundsMetadata(MAX_RAW_CARDINALITY, len(cases), raw_cardinality(plan)),
        cases=tuple(case_envelopes),
    )
    envelope = MatrixResultEnvelope(manifest, tuple(result_references))
    # Force contract serialization here so malformed envelopes fail at the boundary.
    canonical_suite_bytes(envelope)
    return MatrixExecution(plan, cases, results, manifest, envelope)
