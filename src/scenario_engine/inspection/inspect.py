"""Pure transforms from accepted recorded models to inspection documents."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any, Iterable, Mapping

from scenario_engine.batch.models import BatchExecution, BatchPlan, RunRequest
from scenario_engine.composition.models import ComposedExecution, ComposedSuite
from scenario_engine.manifest import ReproducibilityManifest
from scenario_engine.matrix.models import MatrixExecution, MatrixPlan
from scenario_engine.result import ScenarioResult
from scenario_engine.suite import (
    ArtifactOrigin, ArtifactReadModel, ArtifactReference, BatchItemResult,
    BatchManifest, BatchResultEnvelope, CompatibilityRecord, FailureRecord,
    MatrixManifest, MatrixResultEnvelope, RunManifestEnvelope, SuiteManifest,
)

from .errors import UnsupportedInspectionTargetError
from .models import EvidenceAvailability, EvidenceValue, InspectionDocument, InspectionSection
from .redaction import redact_mapping, validate_redacted_keys


def _available(value: Any) -> EvidenceValue:
    return EvidenceValue(EvidenceAvailability.AVAILABLE, value)


def _unavailable(reason: str) -> EvidenceValue:
    return EvidenceValue(EvidenceAvailability.UNAVAILABLE, reason=reason)


def _redacted(reason: str) -> EvidenceValue:
    return EvidenceValue(EvidenceAvailability.REDACTED, reason=reason)


def _document(kind: str, sections: Iterable[tuple[str, EvidenceValue]]) -> InspectionDocument:
    return InspectionDocument(kind, tuple(InspectionSection(name, value) for name, value in sections))


def _reference(value: ArtifactReference | None) -> Any:
    if value is None:
        return None
    return {"kind": value.kind, "identity": value.identity, "sha256": value.sha256}


def _manifest_value(value: ReproducibilityManifest | Mapping[str, Any]) -> Mapping[str, Any]:
    return value.normalized() if isinstance(value, ReproducibilityManifest) else value


def _compatibility_from_manifest(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "artifact_readable": True,
        "artifact_inspectable": True,
        "execution_replay_supported": False,
        "recorded": {
            "domain_pack_versions": value["domain_pack_versions"],
            "dsl_version": value["dsl_version"],
            "engine_version": value["engine_version"],
            "generator_versions": value["generator_versions"],
            "id_algorithm_version": value["id_algorithm_version"],
            "rng_algorithm_version": value["rng_algorithm_version"],
        },
        "replay_code": "replay.engine_version_unsupported",
    }


def inspect_manifest(target: ReproducibilityManifest | ArtifactReadModel) -> InspectionDocument:
    if isinstance(target, ArtifactReadModel):
        if target.origin is not ArtifactOrigin.V1_MANIFEST:
            raise UnsupportedInspectionTargetError("artifact read model is not a v1 manifest")
        value = target.payload
        identity = {"artifact_version": target.artifact_version, "origin": target.origin.value}
    elif isinstance(target, ReproducibilityManifest):
        value = target.normalized()
        identity = {"artifact_version": value["engine_version"], "origin": "v1_manifest"}
    else:
        raise UnsupportedInspectionTargetError("inspect_manifest requires ReproducibilityManifest or v1 manifest read model")
    return _document("v1_manifest", (
        ("schema_identity", _available(identity)),
        ("scenario_identity", _available({"scenario_canonical_hash": value["scenario_canonical_hash"]})),
        ("execution_context", _available({
            "locale": value["locale"], "reference_clock_start": value["reference_clock_start"],
            "root_seed": value["root_seed"], "run_index": value["run_index"],
        })),
        ("compatibility", _available(_compatibility_from_manifest(value))),
        ("input_resource_hashes", _available(value["input_resource_hashes"])),
        ("domain_packs", _available(value["domain_pack_versions"])),
    ))


def inspect_result(target: ScenarioResult | ArtifactReadModel) -> InspectionDocument:
    if isinstance(target, ArtifactReadModel):
        if target.origin is not ArtifactOrigin.V1_RESULT:
            raise UnsupportedInspectionTargetError("artifact read model is not a v1 result")
        value = target.payload
        identity = {"artifact_version": target.artifact_version, "origin": target.origin.value,
                    "scenario_id": value["scenario_id"]}
    elif isinstance(target, ScenarioResult):
        value = target.normalized()
        identity = {"artifact_version": value["manifest"]["engine_version"], "origin": "v1_result",
                    "scenario_id": value["scenario_id"]}
    else:
        raise UnsupportedInspectionTargetError("inspect_result requires ScenarioResult or v1 result read model")
    manifest = value["manifest"]
    provenance = value.get("provenance")
    return _document("v1_result", (
        ("schema_identity", _available(identity)),
        ("scenario_identity", _available({"scenario_canonical_hash": manifest["scenario_canonical_hash"]})),
        ("execution_context", _available({
            "locale": manifest["locale"], "reference_clock_start": manifest["reference_clock_start"],
            "root_seed": manifest["root_seed"], "run_index": manifest["run_index"],
        })),
        ("compatibility", _available(_compatibility_from_manifest(manifest))),
        ("input_resource_hashes", _available(manifest["input_resource_hashes"])),
        ("final_state", _available(value["state"])),
        ("history", _available(value["history"])),
        ("artifacts", _available(value["artifacts"])),
        ("trace", _available(value["history"])),
        ("provenance", _available(provenance) if provenance is not None else _unavailable("not_recorded")),
        ("oracle", _available([item for item in provenance if item.get("kind", "").startswith("oracle")])
         if provenance is not None else _unavailable("not_recorded")),
        ("branch_repeat", _unavailable("not_unambiguously_recorded")),
    ))


def _compatibility(value: CompatibilityRecord) -> Mapping[str, Any]:
    return {
        "execution_contract": value.execution_contract,
        "execution_replay_supported": value.execution_replay.value,
        "plugin_versions": value.plugin_versions,
        "domain_packs": [{"identity": item.identity, "version": item.version,
                          "content_hash": item.content_hash} for item in value.domain_packs],
    }


def inspect_suite(target: SuiteManifest | RunManifestEnvelope | ComposedSuite | ComposedExecution) -> InspectionDocument:
    if isinstance(target, ComposedExecution):
        suite, run = target.suite_manifest, target.run_manifest
        sections = list(_suite_sections(suite))
        sections.append(("run", _available({
            "root_scenario_identity": run.root_scenario_identity,
            "execution_context": _record(run.execution_context),
            "compatibility": _compatibility(run.compatibility),
            "child_manifest": run.child_manifest.normalized() if run.child_manifest else None,
            "child_manifest_reference": _reference(run.child_manifest_reference),
        })))
        return _document("composed_execution", sections)
    if isinstance(target, ComposedSuite):
        sections = list(_suite_sections(target.manifest))
        sections.append(("composition_resolution", _available({
            "module_aliases": [item.alias for item in target.modules],
            "module_content_hashes": {item.alias: item.content_hash for item in target.modules},
            "resolution_order": [item.alias for item in target.modules],
        })))
        return _document("composed_suite", sections)
    if isinstance(target, SuiteManifest):
        return _document("suite_manifest", _suite_sections(target))
    if isinstance(target, RunManifestEnvelope):
        return _document("run_manifest", (
            ("schema_identity", _available({"schema_version": target.schema_version,
                                             "root_scenario_identity": target.root_scenario_identity,
                                             "suite_hash": target.suite_hash})),
            ("execution_context", _available(_record(target.execution_context))),
            ("compatibility", _available(_compatibility(target.compatibility))),
            ("child_manifest_links", _available({
                "embedded": target.child_manifest.normalized() if target.child_manifest else None,
                "reference": _reference(target.child_manifest_reference),
            })),
        ))
    raise UnsupportedInspectionTargetError("unsupported suite inspection target")


def _suite_sections(value: SuiteManifest) -> tuple[tuple[str, EvidenceValue], ...]:
    return (
        ("schema_identity", _available({"schema_version": value.schema_version,
                                         "root_scenario_identity": value.root_scenario_identity})),
        ("composition", _available({
            "composed_hash": value.composed_hash,
            "composition_contract_version": value.composition_contract_version,
            "module_hashes": value.module_hashes,
            "resolution_order": list(value.module_hashes),
        })),
        ("domain_packs", _available([_record(item) for item in value.domain_packs])),
        ("child_manifest_links", _available([_reference(item) for item in value.child_runs])),
    )


def inspect_matrix(target: MatrixPlan | MatrixManifest | MatrixResultEnvelope | MatrixExecution) -> InspectionDocument:
    if isinstance(target, MatrixExecution):
        return _document("matrix_execution", _matrix_manifest_sections(target.manifest) + (
            ("plan", _available(_matrix_plan(target.plan))),
            ("result_links", _available([_reference(item) for item in target.envelope.result_references])),
        ))
    if isinstance(target, MatrixPlan):
        return _document("matrix_plan", (("matrix", _available(_matrix_plan(target))),))
    if isinstance(target, MatrixResultEnvelope):
        return _document("matrix_result", _matrix_manifest_sections(target.manifest) + (
            ("result_links", _available([_reference(item) for item in target.result_references])),
        ))
    if isinstance(target, MatrixManifest):
        return _document("matrix_manifest", _matrix_manifest_sections(target))
    raise UnsupportedInspectionTargetError("unsupported matrix inspection target")


def _matrix_plan(value: MatrixPlan) -> Mapping[str, Any]:
    raw = 1
    for dimension in value.dimensions:
        raw *= len(dimension.values)
    return {
        "suite_identity": value.suite_identity, "suite_hash": value.suite_hash,
        "matrix_plan_identity": value.plan_id,
        "dimensions": [{"name": item.name, "values": item.values} for item in value.dimensions],
        "raw_cardinality": raw, "root_seed": value.root_seed, "locale": value.locale,
    }


def _matrix_manifest_sections(value: MatrixManifest) -> tuple[tuple[str, EvidenceValue], ...]:
    return (
        ("schema_identity", _available({"schema_version": value.schema_version,
                                         "contract_version": value.contract_version,
                                         "suite_identity": value.suite_identity,
                                         "suite_hash": value.suite_hash})),
        ("execution_context", _available(_record(value.execution_context))),
        ("bounds", _available(_record(value.bounds))),
        ("cases", _available([{
            "case_id": item.case.case_id, "original_index": item.case.case_index,
            "ordered_assignment": [[key, item.case.assignment[key]] for key in item.case.assignment],
            "replay_identity": item.case.replay_identity,
            "child_manifest": _reference(item.child_manifest),
            "child_result": _reference(item.child_result),
        } for item in value.cases])),
    )


def inspect_batch(
    target: BatchPlan | BatchManifest | BatchResultEnvelope | BatchExecution, *,
    include_input_values: bool = False, redacted_keys: Iterable[str] | None = None,
) -> InspectionDocument:
    keys = validate_redacted_keys(redacted_keys)
    if not isinstance(include_input_values, bool):
        raise TypeError("include_input_values must be boolean")
    if isinstance(target, BatchExecution):
        sections = list(_batch_manifest_sections(target.envelope.manifest))
        plan_sections = list(_batch_plan_sections(target.plan, include_input_values, keys))
        plan_identity = plan_sections.pop(0)[1]
        sections.append(("plan", plan_identity))
        sections.extend(plan_sections)
        return _document("batch_execution", sections)
    if isinstance(target, BatchPlan):
        return _document("batch_plan", _batch_plan_sections(target, include_input_values, keys))
    if isinstance(target, BatchResultEnvelope):
        return _document("batch_result", _batch_manifest_sections(target.manifest))
    if isinstance(target, BatchManifest):
        return _document("batch_manifest", _batch_manifest_sections(target))
    raise UnsupportedInspectionTargetError("unsupported batch inspection target")


def _batch_plan_sections(value: BatchPlan, include: bool, keys: frozenset[str]) -> tuple[tuple[str, EvidenceValue], ...]:
    requests = [{
        "run_id": item.run_id, "plan_position": item.plan_position,
        "child_identity": item.child_identity, "request_identity": item.request_identity,
        "execution_mode": item.execution_mode.value, "root_seed": item.root_seed,
        "run_index": item.run_index, "locale": item.locale,
    } for item in value.items]
    input_evidence = _available([
        {"run_id": item.run_id, "values": redact_mapping(item.inputs, keys)} for item in value.items
    ]) if include else _redacted("input_values_omitted_by_default")
    return (
        ("schema_identity", _available({"contract_version": "batch.plan/1",
                                         "plan_identity": value.plan_identity, "plan_hash": value.plan_hash})),
        ("execution_options", _available({"fail_fast": value.fail_fast,
                                           "retained_result_bytes": value.retained_result_bytes})),
        ("requests", _available(requests)),
        ("input_values", input_evidence),
    )


def _batch_manifest_sections(value: BatchManifest) -> tuple[tuple[str, EvidenceValue], ...]:
    return (
        ("schema_identity", _available({"schema_version": value.schema_version,
                                         "contract_version": value.contract_version,
                                         "plan_identity": value.plan_identity, "plan_hash": value.plan_hash,
                                         "bundle_identity": value.bundle_identity})),
        ("items", _available([_batch_item(item, position) for position, item in enumerate(value.items)])),
        ("summary", _available({"success": value.success_count, "failure": value.failure_count,
                                 "not_run": value.not_run_count})),
    )


def _batch_item(value: BatchItemResult, position: int) -> Mapping[str, Any]:
    return {"plan_position": position, "run_id": value.run_identity,
            "child_identity": value.child_identity, "status": value.status.value,
            "child_manifest": _reference(value.child_manifest), "child_result": _reference(value.child_result),
            "failure": _failure(value.failure) if value.failure else None}


def inspect_failure(target: FailureRecord | BatchItemResult) -> InspectionDocument:
    if isinstance(target, BatchItemResult):
        if target.failure is None:
            return _document("failure", (("failure", _unavailable("no_failure_recorded")),))
        return _document("failure", (("subject", _available({"run_id": target.run_identity,
                                                               "child_identity": target.child_identity})),
                                     ("failure", _available(_failure(target.failure)))))
    if isinstance(target, FailureRecord):
        return _document("failure", (("failure", _available(_failure(target))),))
    raise UnsupportedInspectionTargetError("inspect_failure requires a stable FailureRecord or BatchItemResult")


def _failure(value: FailureRecord) -> Mapping[str, Any]:
    return {"family": value.family, "code": value.code, "message": value.message}


def _record(value: Any) -> Mapping[str, Any]:
    if not is_dataclass(value):
        raise TypeError("record conversion requires a dataclass")
    result = {}
    for item in fields(value):
        current = getattr(value, item.name)
        if isinstance(current, Enum):
            current = current.value
        result[item.name] = current
    return result


def inspect(target: Any, **kwargs: Any) -> InspectionDocument:
    """Compact explicit dispatcher over all supported already-recorded target kinds."""
    if isinstance(target, (ScenarioResult, ArtifactReadModel)):
        if isinstance(target, ArtifactReadModel) and target.origin is ArtifactOrigin.V1_MANIFEST:
            return inspect_manifest(target)
        return inspect_result(target)
    if isinstance(target, ReproducibilityManifest):
        return inspect_manifest(target)
    if isinstance(target, (SuiteManifest, RunManifestEnvelope, ComposedSuite, ComposedExecution)):
        return inspect_suite(target)
    if isinstance(target, (MatrixPlan, MatrixManifest, MatrixResultEnvelope, MatrixExecution)):
        return inspect_matrix(target)
    if isinstance(target, (BatchPlan, BatchManifest, BatchResultEnvelope, BatchExecution)):
        return inspect_batch(target, **kwargs)
    if isinstance(target, (FailureRecord, BatchItemResult)):
        return inspect_failure(target)
    raise UnsupportedInspectionTargetError(f"unsupported inspection target: {type(target).__name__}")
