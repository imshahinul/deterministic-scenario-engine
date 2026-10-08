"""Thin, bounded CLI orchestration over accepted Scenario Engine APIs."""

from __future__ import annotations

import argparse
from enum import Enum, IntEnum
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping, Sequence

from scenario_engine.batch import (
    DEFAULT_RETAINED_RESULT_BYTES, BatchError, BatchPlan, ExecutionMode,
    RunRequest, execute_batch,
)
from scenario_engine._version import ENGINE_VERSION
from scenario_engine.canonical import canonical_scenario_hash
from scenario_engine.composition import (
    ComposedSuite, CompositionBoundError, CompositionError,
    CompositionPathError, CompositionRootEscapeError, ModuleNotFoundError as CompositionModuleNotFoundError,
    UnsupportedCompositionSourceError,
    execute_composed_suite, load_composed_suite,
)
from scenario_engine.compatibility_fixtures import export_compatibility_fixtures
from scenario_engine.diff import (
    DEFAULT_MAX_DIFF_RECORDS, DiffBoundError, DiffError, canonical_diff_bytes,
    render_diff_text, semantic_diff,
)
from scenario_engine.diagnostics import (
    HumanDiagnostic, bounded_text, render_error_envelope, render_human_diagnostic,
)
from scenario_engine.definition_diff import compare_definitions, render_definition_diff
from scenario_engine.dsl import (
    CompiledScenarioV2, DSLError, UnsupportedDSL2ExecutionError,
    compile_document, parse_yaml, replay_scenario, run_scenario,
)
from scenario_engine.errors import ScenarioEngineError
from scenario_engine.evidence import (
    BUNDLE_INDEX_FILENAME, ArtifactDescriptor, EvidenceBoundError, EvidenceContractError,
    EvidenceDestinationError, EvidenceExportBoundError, EvidenceFilesystemError,
    EvidenceIndexError, EvidenceIntegrityError, EvidenceMigrationError,
    EvidencePublicationError, EvidenceSourceIntegrityError,
    EvidenceValidationBoundError, EvidenceValidationError, MigrationDisposition,
    canonical_migration_plan_bytes, canonical_migration_result_bytes,
    execute_lossless_migration, export_evidence_bundle, plan_migration,
    read_evidence_bundle,
)
from scenario_engine.inspection import (
    InspectionBoundError, InspectionError, canonical_explanation_bytes,
    canonical_inspection_bytes, explain_result, inspect,
)
from scenario_engine.impact import analyze_impact, render_impact_analysis
from scenario_engine.manifest import (
    ReplayCompatibilityError, ReplayCompatibilityReason, ReproducibilityManifest,
)
from scenario_engine.resources import ResourceResolutionError
from scenario_engine.scaffolding import (
    DEFAULT_SCAFFOLD_PROVIDER, ScaffoldError, ScaffoldRequest, scaffold_scenario,
)
from scenario_engine.matrix import (
    MatrixDimension, MatrixError, MatrixPlan, execute_matrix,
    execute_matrix_case, expand_matrix,
)
from scenario_engine.suite import (
    ArtifactBoundError, ArtifactReadError, CompatibilityRecord, ExecutionContext,
    ExecutionReplaySupport, RunManifestEnvelope, SuiteSerializationError,
    UnsupportedReplayContractError, canonical_suite_bytes, parse_suite_bytes,
    publish_suite_bytes, read_v1_manifest_bytes, read_v1_result_bytes,
)
from scenario_engine.trace_view import (
    TRACE_VIEW_MAX_INPUT_BYTES, TraceViewError, render_trace_view,
)
from scenario_engine.values import normalize


MAX_CLI_INPUT_BYTES = 16 * 1024 * 1024
MAX_AUXILIARY_JSON_BYTES = 1 * 1024 * 1024
MAX_DIAGNOSTIC_CHARS = 4096
MAX_RENDERED_OUTPUT_BYTES = 256 * 1024 * 1024
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")


class CLIExitCode(IntEnum):
    SUCCESS = 0
    DIFFERENT = 1
    USAGE = 2
    VALIDATION = 3
    EXECUTION = 4
    REPLAY_COMPATIBILITY = 5
    SECURITY_OR_BOUND = 6
    IO = 7
    INTERNAL = 8


class PathReason(str, Enum):
    """Stable public classifications for local filesystem trust-boundary failures."""

    PATH_NOT_ABSOLUTE = "PATH_NOT_ABSOLUTE"
    PATH_REMOTE_FORBIDDEN = "PATH_REMOTE_FORBIDDEN"
    PATH_OUTSIDE_ALLOWED_ROOT = "PATH_OUTSIDE_ALLOWED_ROOT"
    PATH_NOT_FOUND = "PATH_NOT_FOUND"
    PATH_UNSAFE = "PATH_UNSAFE"
    INVALID_DESTINATION = "INVALID_DESTINATION"
    DESTINATION_ALREADY_EXISTS = "DESTINATION_ALREADY_EXISTS"
    DESTINATION_PARENT_MISSING = "DESTINATION_PARENT_MISSING"
    DESTINATION_NOT_WRITABLE = "DESTINATION_NOT_WRITABLE"


class _CLIError(Exception):
    def __init__(
        self, message: str, code: CLIExitCode, *, path_reason: PathReason | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.path_reason = path_reason


class _Parser(argparse.ArgumentParser):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("formatter_class", argparse.RawDescriptionHelpFormatter)
        super().__init__(*args, **kwargs)

    def error(self, message: str) -> None:
        raise _CLIError("invalid command-line arguments", CLIExitCode.USAGE)


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="scenario",
        description="Deterministic Scenario Engine installed-package public workflow command surface.",
        epilog="Use 'scenario COMMAND --help' for each public workflow's command details.",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="emit canonical JSON; errors use the scenario.error/1 machine envelope",
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    validate = commands.add_parser("validate", help="validate a scenario without execution")
    validate.description = (
        "Validate a scenario without execution. Routine authoring failures report a stable "
        "diagnostic code and, when available, a scenario.semantic-address/1 path."
    )
    _source(validate)

    scaffold = commands.add_parser(
        "scaffold", help="propose offline deterministic DSL for later review and validation",
        description=(
            "Propose deterministic DSL 1 authoring material with the offline default provider. "
            "No API key or runtime LLM is required. The command never executes the draft: treat "
            "generated DSL as untrusted, inspect it, pass it through ordinary validation, and "
            "human-review/freeze it before a later explicit run."
        ),
    )
    scaffold.add_argument("scenario_id", help="bounded scenario identifier")
    scaffold.add_argument(
        "--step", dest="step_ids", action="append", required=True,
        help="ordered step identifier; repeat for additional steps",
    )
    scaffold.add_argument(
        "--clock-start", default="2026-01-01T00:00:00Z",
        help="explicit ISO-8601 reference clock start",
    )
    scaffold.add_argument(
        "--provider", default=DEFAULT_SCAFFOLD_PROVIDER,
        help=f"authoring provider (default: {DEFAULT_SCAFFOLD_PROVIDER}; offline)",
    )

    run = commands.add_parser(
        "run", help="execute a scenario and optionally write a suite.run/1 replay artifact",
        description=(
            "Execute a validated scenario and emit its normal scenario.result/1 result. "
            "--replay-out separately writes a supported suite.run/1 replay artifact; a normal "
            "result is not automatically replayable."
        ),
    )
    _source(run)
    _execution(run)
    run.add_argument(
        "--replay-out", metavar="PATH",
        help="write a supported suite.run/1 replay artifact to an absent local path",
    )

    replay = commands.add_parser(
        "replay", help="replay a supported suite.run/1 artifact with fail-closed compatibility",
        description=(
            "Replay a supported suite.run/1 recorded manifest. Incompatibility exits 5 and "
            "reports a stable replay reason code on stderr. The original external inputs may "
            "be required: --inputs must match the recorded input fingerprint where applicable. "
            "Missing required replay data fails closed with exit 5."
        ),
    )
    replay.add_argument("source", help="local suite.run/1 replay artifact path or - for stdin")
    replay.add_argument("--scenario", required=True, help="explicit local scenario YAML path")
    replay.add_argument(
        "--inputs",
        help="bounded JSON object containing original external inputs required by the artifact",
    )

    trace_view = commands.add_parser(
        "trace-view", help="render a self-contained offline HTML trace view",
        description=("Render one supported local result or suite.run/1 artifact as one read-only "
                     "HTML file. No server, network, telemetry, or source mutation is used."),
    )
    trace_view.add_argument("source", help="absolute local result or suite.run/1 JSON path")
    trace_view.add_argument("--out", required=True, help="absent absolute local HTML output path")

    hash_command = commands.add_parser("hash", help="print semantic scenario identity")
    _source(hash_command)

    inspect_command = commands.add_parser(
        "inspect", help="summarize normalized evidence from a supported recorded artifact",
        description="Read and summarize supported recorded evidence without re-executing it.",
    )
    inspect_command.add_argument("source", help="local artifact JSON path or - for stdin")
    inspect_command.add_argument(
        "--kind", choices=("result", "manifest", "suite"), default="result",
        help="artifact contract",
    )

    explain = commands.add_parser(
        "explain", help="explain step and state-change evidence in a recorded result",
        description="Explain available causal step and state-change evidence from a supported result without inventing missing facts.",
    )
    explain.add_argument("source", help="local result JSON path or - for stdin")

    difference = commands.add_parser(
        "diff", help="compare two recorded execution artifacts (not scenario definitions)",
        description="Semantically compare two supported recorded execution artifacts. Use diff-definition for validated DSL definitions.",
    )
    difference.add_argument("left", help="first local artifact JSON path or -")
    difference.add_argument("right", help="second local artifact JSON path or -")
    difference.add_argument("--kind", choices=("result", "manifest", "suite"), default="result")
    difference.add_argument("--mode", choices=("first", "complete"), default="first")
    difference.add_argument("--max-records", type=int, default=DEFAULT_MAX_DIFF_RECORDS)

    definition_diff = commands.add_parser(
        "diff-definition", help="structurally compare two validated scenario definitions",
        description=(
            "Compare validated scenario definitions structurally, independent of YAML formatting. "
            "Mapping-key order and formatting-only changes are ignored; changes use "
            "scenario.semantic-address/1 addresses. This is distinct from 'scenario diff', "
            "which compares execution artifacts, and does not run impact analysis."
        ),
    )
    definition_diff.add_argument("left", help="first local scenario YAML path or -")
    definition_diff.add_argument("right", help="second local scenario YAML path or -")

    impact = commands.add_parser(
        "impact", help="conservatively analyze possible impact of definition changes",
        description=("Statically analyze two validated scenario definitions using their authoritative "
                     "structural diff. Classifications are DIRECT, TRANSITIVE_POSSIBLE, and "
                     "UNKNOWN. Reports are may-impact only: UNKNOWN does not mean unaffected "
                     "(UNKNOWN != UNAFFECTED), "
                     "and amplification is an affected-entity fraction, not a probability. No "
                     "behavioral-equivalence claim is made."),
    )
    impact.add_argument("left", help="before local scenario YAML path or -")
    impact.add_argument("right", help="target local scenario YAML path or -")

    matrix = commands.add_parser("matrix", help="expand or execute a deterministic matrix")
    _source(matrix)
    matrix.add_argument("--seed", required=True, help="explicit root seed")
    matrix.add_argument("--locale", default="C", help="explicit locale coordinate")
    matrix.add_argument("--dimensions", required=True, help="bounded JSON dimension list")
    matrix.add_argument("--filters", help="bounded JSON filter list")
    matrix.add_argument("--inputs", help="bounded JSON object")
    choice = matrix.add_mutually_exclusive_group()
    choice.add_argument("--describe", action="store_true", help="expand without execution")
    choice.add_argument("--case", help="execute one exact stable case ID")

    batch = commands.add_parser("batch", help="execute an explicit deterministic run plan")
    batch.add_argument("source", help="local bounded batch-plan JSON path or - for stdin")
    batch.add_argument("--workers", type=int, default=1, help="bounded execution strategy")
    batch.add_argument("--max-in-flight", type=int, default=64, help="bounded scheduling window")

    compatibility_fixtures = commands.add_parser(
        "compatibility-fixtures",
        help="discover and export the frozen public compatibility fixture corpus",
        description=(
            "Export the frozen public compatibility fixture corpus containing current, historical, "
            "and synthetic artifacts for replay, inspect, migrate, and compatibility exercises. "
            "The export is copied from immutable installed package resources; no source checkout "
            "or network access is used."
        ),
        epilog=(
            "Export to an absent absolute local directory with: "
            "scenario compatibility-fixtures export --out /absolute/path"
        ),
    )
    fixture_actions = compatibility_fixtures.add_subparsers(
        dest="fixture_action", required=True, metavar="ACTION"
    )
    fixture_export = fixture_actions.add_parser(
        "export",
        help="copy the complete frozen corpus to an absent local directory",
        description=(
            "Copy the complete frozen current, historical, and synthetic compatibility fixture "
            "corpus from installed package resources for replay, inspect, and migrate exercises."
        ),
    )
    fixture_export.add_argument(
        "--out", required=True,
        help="absent absolute local filesystem path for the exported frozen fixture directory",
    )

    export = commands.add_parser("export", help="copy a verified local evidence bundle to an absent destination")
    export.add_argument("source", help="absolute local filesystem path to an evidence bundle root")
    export.add_argument("destination", help="absent absolute local filesystem path for the destination directory")

    verify = commands.add_parser("verify", help="verify integrity of a local evidence bundle")
    verify.add_argument("bundle", help="absolute local filesystem path to an evidence bundle root")

    migrate = commands.add_parser("migrate", help="execute a planned lossless migration")
    migrate.add_argument("source", help="absolute local filesystem path to the source artifact")
    migrate.add_argument("destination", help="absent absolute local filesystem path for the destination directory")
    migrate.add_argument("--artifact-kind", required=True, help="explicit artifact kind")
    migrate.add_argument("--schema-version", required=True, help="explicit source schema contract")
    migrate.add_argument("--product-version", required=True, help="explicit source product version")
    migrate.add_argument("--source-sha256", required=True, help="exact lowercase source SHA-256")
    migrate.add_argument("--target-contract", default="evidence.bundle/1", help="explicit target contract")
    migrate.add_argument("--dry-run", action="store_true", help="plan without creating a destination")
    return parser


def _source(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("source", help="explicit local scenario YAML path or - for stdin")
    parser.add_argument("--root", help="absolute local filesystem path to the composition root")


def _execution(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--seed", required=True, help="explicit root seed")
    parser.add_argument("--run-index", type=int, default=0, help="nonnegative run index")
    parser.add_argument("--locale", default="C", help="explicit locale coordinate")
    parser.add_argument("--inputs", help="bounded JSON object")


def _reject_remote(source: str) -> None:
    lowered = source.lower()
    if lowered.startswith(("http://", "https://")) or (_SCHEME.match(source) and source != "-"):
        raise _CLIError(
            "remote and URI-like input sources are forbidden", CLIExitCode.SECURITY_OR_BOUND,
            path_reason=PathReason.PATH_REMOTE_FORBIDDEN,
        )


def _require_absolute_local(value: str, label: str) -> Path:
    """Apply public path-form checks before delegating to authoritative filesystem checks."""
    _reject_remote(value)
    try:
        path = Path(value)
    except (TypeError, ValueError):
        reason = PathReason.INVALID_DESTINATION if "destination" in label else PathReason.PATH_UNSAFE
        raise _CLIError(
            f"{label} is not a valid local filesystem path", CLIExitCode.SECURITY_OR_BOUND,
            path_reason=reason,
        ) from None
    if not path.is_absolute():
        raise _CLIError(
            f"{label} must be an absolute local filesystem path",
            CLIExitCode.SECURITY_OR_BOUND, path_reason=PathReason.PATH_NOT_ABSOLUTE,
        )
    return path


def _read(source: str, *, limit: int = MAX_CLI_INPUT_BYTES, stdin_used: list[bool] | None = None) -> bytes:
    _reject_remote(source)
    if source == "-":
        if stdin_used is not None and stdin_used[0]:
            raise _CLIError("at most one input may use stdin", CLIExitCode.USAGE)
        if stdin_used is not None:
            stdin_used[0] = True
        data = sys.stdin.buffer.read(limit + 1)
    else:
        path = Path(source)
        try:
            if not path.exists():
                raise _CLIError(
                    "input source was not found", CLIExitCode.IO,
                    path_reason=PathReason.PATH_NOT_FOUND,
                )
            if not path.is_file():
                raise _CLIError(
                    "input source must be a regular local file", CLIExitCode.IO,
                    path_reason=PathReason.PATH_UNSAFE,
                )
            if path.stat().st_size > limit:
                raise _CLIError(f"input exceeds {limit} bytes", CLIExitCode.SECURITY_OR_BOUND)
            data = path.read_bytes()
        except _CLIError:
            raise
        except OSError:
            raise _CLIError("unable to read input source", CLIExitCode.IO) from None
    if len(data) > limit:
        raise _CLIError(f"input exceeds {limit} bytes", CLIExitCode.SECURITY_OR_BOUND)
    return data


def _text(data: bytes, label: str = "input") -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise _CLIError(f"{label} must be UTF-8", CLIExitCode.VALIDATION) from None


def _json_argument(value: str | None, expected: type, default: Any) -> Any:
    if value is None:
        return default
    if len(value.encode("utf-8")) > MAX_AUXILIARY_JSON_BYTES:
        raise _CLIError("auxiliary JSON exceeds its byte bound", CLIExitCode.SECURITY_OR_BOUND)
    try:
        result = json.loads(value, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (json.JSONDecodeError, ValueError):
        raise _CLIError("auxiliary data must be strict JSON", CLIExitCode.USAGE) from None
    if not isinstance(result, expected):
        raise _CLIError(f"auxiliary JSON must be a {expected.__name__}", CLIExitCode.USAGE)
    return result


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise ValueError("non-finite JSON number")


def _load_target(source: str, root: str | None) -> tuple[Any, bool]:
    _reject_remote(source)
    if source == "-":
        if root is not None:
            raise _CLIError(
                "composed stdin is unsupported by the accepted local-file resolver",
                CLIExitCode.SECURITY_OR_BOUND,
            )
        document = parse_yaml(_text(_read(source)))
        return compile_document(document), False
    composition_root = Path(root) if root is not None else Path(source).parent
    if root is not None and not composition_root.is_absolute():
        raise _CLIError(
            "composition root must be an absolute local filesystem path",
            CLIExitCode.SECURITY_OR_BOUND, path_reason=PathReason.PATH_NOT_ABSOLUTE,
        )
    direct_error: Exception | None = None
    if root is None:
        try:
            document = parse_yaml(_text(_read(source)))
            return compile_document(document), False
        except DSLError as error:
            direct_error = error
    try:
        return load_composed_suite(source, composition_root=composition_root.resolve()), True
    except CompositionError:
        if direct_error is not None:
            raise direct_error
        raise


def _seed(value: str) -> str | int:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return value
    if isinstance(parsed, bool) or not isinstance(parsed, (str, int)):
        return value
    return parsed


def _result_output(value: Any) -> bytes:
    return value.to_json_bytes()


def _validate(args: argparse.Namespace) -> tuple[bytes, bytes]:
    target, composed = _load_target(args.source, args.root)
    identity = target.composed_hash if composed else canonical_scenario_hash(target)
    return _canonical({"command": "validate", "identity": identity, "valid": True}), (
        f"valid {'composed suite' if composed else 'scenario'} {identity}\n".encode("utf-8")
    )


def _scaffold(args: argparse.Namespace) -> tuple[bytes, bytes]:
    result = scaffold_scenario(
        ScaffoldRequest(args.scenario_id, tuple(args.step_ids), args.clock_start),
        provider=args.provider,
    )
    return _canonical(result.to_jsonable()), result.proposed_dsl.encode("utf-8")


def _run(args: argparse.Namespace) -> tuple[bytes, bytes]:
    target, composed = _load_target(args.source, args.root)
    inputs = _json_argument(args.inputs, dict, None)
    if composed:
        if args.replay_out is not None:
            raise UnsupportedReplayContractError("composed-cli-run", ())
        result = execute_composed_suite(
            target, _seed(args.seed), run_index=args.run_index, locale=args.locale, inputs=inputs,
        ).result
    else:
        result = run_scenario(
            target, _seed(args.seed), run_index=args.run_index, locale=args.locale, inputs=inputs,
        )
    if args.replay_out is not None:
        _write_replay_artifact(args.replay_out, _replay_envelope(result))
    data = _result_output(result)
    return data, data


def _replay_envelope(result: Any) -> RunManifestEnvelope:
    manifest = result.manifest
    plugin_versions = {
        key.removeprefix("plugin:"): value
        for key, value in manifest.generator_versions.items()
        if key.startswith("plugin:")
    }
    return RunManifestEnvelope(
        root_scenario_identity=result.scenario_id,
        execution_context=ExecutionContext(
            manifest.root_seed, manifest.run_index, manifest.locale,
            manifest.reference_clock_start,
        ),
        compatibility=CompatibilityRecord(
            f"scenario-engine/{manifest.engine_version}",
            ExecutionReplaySupport.SUPPORTED,
            plugin_versions=plugin_versions,
        ),
        child_manifest=manifest,
    )


def _write_replay_artifact(destination: str, envelope: RunManifestEnvelope) -> None:
    _reject_remote(destination)
    if destination == "-":
        raise _CLIError("replay output requires an explicit local path", CLIExitCode.USAGE)
    path = Path(destination)
    try:
        publish_suite_bytes(canonical_suite_bytes(envelope), path)
    except FileExistsError:
        raise _CLIError(
            "replay output path must not already exist", CLIExitCode.IO,
            path_reason=PathReason.DESTINATION_ALREADY_EXISTS,
        ) from None
    except FileNotFoundError:
        raise _CLIError(
            "replay output parent directory does not exist", CLIExitCode.IO,
            path_reason=PathReason.DESTINATION_PARENT_MISSING,
        ) from None
    except OSError:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        raise _CLIError(
            "unable to publish replay artifact", CLIExitCode.IO,
            path_reason=PathReason.DESTINATION_NOT_WRITABLE,
        ) from None


def _manifest(value: Mapping[str, Any]) -> ReproducibilityManifest:
    return ReproducibilityManifest(**dict(value))


def _replay(args: argparse.Namespace) -> tuple[bytes, bytes]:
    artifact = _read(args.source)
    scenario = _text(_read(args.scenario), "scenario")
    inputs = _json_argument(args.inputs, dict, None)
    recognized_envelope = _require_supported_replay_schema(artifact)
    try:
        suite_value = parse_suite_bytes(artifact)
    except SuiteSerializationError:
        if recognized_envelope:
            raise ReplayCompatibilityError(
                "suite.run/1 replay data is incomplete or invalid",
                reason=ReplayCompatibilityReason.REPLAY_DATA_INCOMPLETE,
                artifact_contract="suite.run/1",
                remediation="SUPPLY_COMPLETE_REPLAY_DATA",
                migration=ReplayCompatibilityReason.MIGRATION_UNAVAILABLE,
            ) from None
        suite_value = None
    if isinstance(suite_value, RunManifestEnvelope):
        suite_value.compatibility.require_execution_replay()
        if suite_value.child_manifest is None:
            raise ReplayCompatibilityError(
                "embedded reproducibility manifest is required",
                reason=ReplayCompatibilityReason.REPLAY_DATA_INCOMPLETE,
                artifact_contract=suite_value.schema_version,
                remediation="SUPPLY_COMPLETE_REPLAY_DATA",
                migration=ReplayCompatibilityReason.MIGRATION_UNAVAILABLE,
                missing=("child_manifest",),
            )
        manifest = suite_value.child_manifest
        _require_replay_compatibility(suite_value, scenario)
    else:
        try:
            historical_result = read_v1_result_bytes(artifact)
        except ArtifactReadError:
            historical_result = None
        if historical_result is not None:
            recorded_version = historical_result.payload["manifest"]["engine_version"]
            raise UnsupportedReplayContractError(
                recorded_version, (f"scenario-engine/{ENGINE_VERSION}",),
            )
        read = read_v1_manifest_bytes(artifact)
        read.require_execution_replay()
        manifest = _manifest(read.payload)
    try:
        result = replay_scenario(scenario, manifest, inputs=inputs)
    except ResourceResolutionError:
        raise ReplayCompatibilityError(
            "required external replay inputs are missing or cannot be resolved",
            reason=ReplayCompatibilityReason.REPLAY_DATA_INCOMPLETE,
            artifact_contract="suite.run/1",
            remediation="PROVIDE_REQUIRED_REPLAY_INPUTS",
            migration=ReplayCompatibilityReason.MIGRATION_UNAVAILABLE,
            missing=("--inputs",),
        ) from None
    data = result.to_json_bytes()
    return data, data


def _trace_view(args: argparse.Namespace) -> tuple[bytes, bytes]:
    source = _require_absolute_local(args.source, "trace-view source")
    destination = _require_absolute_local(args.out, "trace-view destination")
    try:
        data = _read(str(source), limit=TRACE_VIEW_MAX_INPUT_BYTES)
    except _CLIError as error:
        if error.code is CLIExitCode.SECURITY_OR_BOUND and str(error).startswith("input exceeds"):
            raise TraceViewError("TRACE_INPUT_TOO_LARGE", "trace-view input exceeds its byte bound") from None
        raise
    try:
        raw = json.loads(_text(data), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (json.JSONDecodeError, ValueError):
        raise TraceViewError("TRACE_INPUT_UNSUPPORTED", "trace-view input must be strict supported JSON") from None
    artifact: Any
    if isinstance(raw, Mapping) and raw.get("$model") == "RunManifestEnvelope":
        try:
            artifact = parse_suite_bytes(data)
        except SuiteSerializationError:
            raise TraceViewError("TRACE_INPUT_UNSUPPORTED", "suite.run/1 trace input is invalid") from None
        if not isinstance(artifact, RunManifestEnvelope):
            raise TraceViewError("TRACE_INPUT_UNSUPPORTED", "suite artifact is not suite.run/1")
    else:
        try:
            artifact = read_v1_result_bytes(data)
        except (ArtifactReadError, SuiteSerializationError):
            raise TraceViewError("TRACE_INPUT_UNSUPPORTED", "artifact is not a supported v1 result") from None
    rendered = render_trace_view(artifact)
    try:
        publish_suite_bytes(rendered, destination)
    except FileExistsError:
        raise _CLIError("trace-view output path must not already exist", CLIExitCode.IO,
                        path_reason=PathReason.DESTINATION_ALREADY_EXISTS) from None
    except FileNotFoundError:
        raise _CLIError("trace-view output parent directory does not exist", CLIExitCode.IO,
                        path_reason=PathReason.DESTINATION_PARENT_MISSING) from None
    except OSError:
        destination.unlink(missing_ok=True)
        raise _CLIError("unable to publish trace-view output", CLIExitCode.IO,
                        path_reason=PathReason.DESTINATION_NOT_WRITABLE) from None
    summary = _canonical({"contract": "scenario.trace-view/1", "output": "html", "written": True})
    return summary, f"wrote self-contained offline trace view ({len(rendered)} bytes)\n".encode()


def _require_supported_replay_schema(artifact: bytes) -> bool:
    """Classify safely readable replay schema metadata before strict model parsing."""
    try:
        raw = json.loads(
            artifact.decode("utf-8"), object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return False
    if not isinstance(raw, Mapping) or raw.get("$model") != "RunManifestEnvelope":
        return False
    received = raw.get("schema_version")
    if received is None:
        raise ReplayCompatibilityError(
            "replay artifact contract coordinate is missing",
            reason=ReplayCompatibilityReason.REPLAY_DATA_INCOMPLETE,
            remediation="SUPPLY_COMPLETE_REPLAY_DATA",
            migration=ReplayCompatibilityReason.MIGRATION_UNAVAILABLE,
            missing=("schema_version",),
        )
    if received != "suite.run/1":
        raise ReplayCompatibilityError(
            "replay artifact contract is unsupported",
            reason=ReplayCompatibilityReason.MANIFEST_VERSION_UNSUPPORTED,
            artifact_contract=str(received) if received is not None else None,
            expected="suite.run/1",
            received=str(received) if received is not None else "missing",
            remediation="USE_SUPPORTED_MANIFEST_OR_MIGRATION",
            migration=ReplayCompatibilityReason.MIGRATION_UNAVAILABLE,
        )
    return True


def _require_replay_compatibility(envelope: RunManifestEnvelope, scenario: str) -> None:
    manifest = envelope.child_manifest
    if manifest is None:
        raise ReplayCompatibilityError(
            "child manifest is required",
            artifact_contract=envelope.schema_version,
            remediation="SUPPLY_COMPLETE_REPLAY_DATA",
            migration=ReplayCompatibilityReason.MIGRATION_UNAVAILABLE,
            missing=("child_manifest",),
        )
    expected_contract = f"scenario-engine/{ENGINE_VERSION}"
    if envelope.compatibility.execution_contract != expected_contract:
        raise ReplayCompatibilityError(
            "execution_contract mismatch",
            reason=ReplayCompatibilityReason.ENGINE_VERSION_UNSUPPORTED,
            artifact_contract=envelope.schema_version,
            expected=expected_contract,
            received=envelope.compatibility.execution_contract,
            remediation="USE_SUPPORTED_ENGINE",
            migration=ReplayCompatibilityReason.MIGRATION_UNAVAILABLE,
        )
    compiled = compile_document(parse_yaml(scenario))
    if isinstance(compiled, CompiledScenarioV2):
        raise ReplayCompatibilityError(
            "DSL 2 replay is unsupported in Phase 5.1",
            reason=ReplayCompatibilityReason.ENGINE_VERSION_UNSUPPORTED,
            artifact_contract=envelope.schema_version, expected="DSL 1 / Engine 1 replay",
            received="DSL 2 validation-only definition", remediation="USE_SUPPORTED_ENGINE",
            migration=ReplayCompatibilityReason.MIGRATION_UNAVAILABLE,
        )
    if envelope.root_scenario_identity != compiled.scenario_id:
        raise ReplayCompatibilityError(
            "root_scenario_identity mismatch",
            reason=ReplayCompatibilityReason.SCENARIO_MISMATCH,
            artifact_contract=envelope.schema_version,
            scenario_expected=envelope.root_scenario_identity,
            scenario_received=compiled.scenario_id,
            remediation="SUPPLY_EXACT_SCENARIO",
            migration=ReplayCompatibilityReason.MIGRATION_UNAVAILABLE,
        )
    context = envelope.execution_context
    coordinates = {
        "root_seed": manifest.root_seed,
        "run_index": manifest.run_index,
        "locale": manifest.locale,
        "reference_clock_start": manifest.reference_clock_start,
    }
    for field, expected in coordinates.items():
        if getattr(context, field) != expected:
            raise ReplayCompatibilityError(
                f"execution_context {field} mismatch",
                artifact_contract=envelope.schema_version,
                expected=_diagnostic_value(expected),
                received=_diagnostic_value(getattr(context, field)),
                remediation="SUPPLY_COMPLETE_REPLAY_DATA",
                migration=ReplayCompatibilityReason.MIGRATION_UNAVAILABLE,
                missing=(field,),
            )
    plugin_versions = {
        key.removeprefix("plugin:"): value
        for key, value in manifest.generator_versions.items()
        if key.startswith("plugin:")
    }
    if dict(envelope.compatibility.plugin_versions) != plugin_versions:
        raise ReplayCompatibilityError(
            "plugin_versions mismatch", artifact_contract=envelope.schema_version,
            remediation="SUPPLY_COMPLETE_REPLAY_DATA",
            migration=ReplayCompatibilityReason.MIGRATION_UNAVAILABLE,
            missing=("plugin_versions",),
        )
    recorded_packs = {item.identity: item.version for item in envelope.compatibility.domain_packs}
    if recorded_packs != dict(manifest.domain_pack_versions):
        raise ReplayCompatibilityError(
            "domain_pack_versions mismatch", artifact_contract=envelope.schema_version,
            remediation="SUPPLY_COMPLETE_REPLAY_DATA",
            migration=ReplayCompatibilityReason.MIGRATION_UNAVAILABLE,
            missing=("domain_pack_versions",),
        )


def _diagnostic_value(value: Any) -> str | int:
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        return value
    return _canonical(value).decode("utf-8")


def _hash(args: argparse.Namespace) -> tuple[bytes, bytes]:
    target, composed = _load_target(args.source, args.root)
    identity = target.composed_hash if composed else canonical_scenario_hash(target)
    return _canonical({"hash": identity, "kind": "composition" if composed else "scenario"}), (identity + "\n").encode()


def _artifact(source: str, kind: str, stdin_used: list[bool] | None = None) -> Any:
    data = _read(source, stdin_used=stdin_used)
    if kind == "result":
        return read_v1_result_bytes(data)
    if kind == "manifest":
        return read_v1_manifest_bytes(data)
    return parse_suite_bytes(data)


def _inspect(args: argparse.Namespace) -> tuple[bytes, bytes]:
    data = canonical_inspection_bytes(inspect(_artifact(args.source, args.kind)))
    return data, _pretty(data)


def _explain(args: argparse.Namespace) -> tuple[bytes, bytes]:
    data = canonical_explanation_bytes(explain_result(_artifact(args.source, "result")))
    return data, _pretty(data)


def _diff(args: argparse.Namespace) -> tuple[bytes, bytes, CLIExitCode]:
    used = [False]
    left = _artifact(args.left, args.kind, used)
    right = _artifact(args.right, args.kind, used)
    document = semantic_diff(left, right, mode=args.mode, max_records=args.max_records)
    code = CLIExitCode.SUCCESS if document.equal else CLIExitCode.DIFFERENT
    return canonical_diff_bytes(document), (render_diff_text(document) + "\n").encode("utf-8"), code


def _diff_definition(args: argparse.Namespace) -> tuple[bytes, bytes]:
    used = [False]
    left = parse_yaml(_text(_read(args.left, stdin_used=used), "left scenario"))
    right = parse_yaml(_text(_read(args.right, stdin_used=used), "right scenario"))
    document = compare_definitions(left, right)
    return document.to_json_bytes(), (render_definition_diff(document) + "\n").encode("utf-8")


def _impact(args: argparse.Namespace) -> tuple[bytes, bytes]:
    used = [False]
    left = parse_yaml(_text(_read(args.left, stdin_used=used), "before scenario"))
    right = parse_yaml(_text(_read(args.right, stdin_used=used), "target scenario"))
    document = analyze_impact(left, right)
    return document.to_json_bytes(), (render_impact_analysis(document) + "\n").encode("utf-8")


def _matrix_plan(args: argparse.Namespace) -> MatrixPlan:
    target, composed = _load_target(args.source, args.root)
    raw_dimensions = _json_argument(args.dimensions, list, ())
    dimensions = []
    for value in raw_dimensions:
        if not isinstance(value, Mapping) or set(value) != {"name", "values"} or not isinstance(value["values"], list):
            raise _CLIError("each matrix dimension requires name and values", CLIExitCode.USAGE)
        dimensions.append(MatrixDimension(value["name"], tuple(value["values"])))
    filters = _json_argument(args.filters, list, ())
    identity = target.root_scenario_identity if composed else target.scenario_id
    suite_hash = target.composed_hash if composed else canonical_scenario_hash(target)
    return MatrixPlan(
        identity, suite_hash, tuple(dimensions), tuple(filters), _seed(args.seed),
        args.locale, target,
    )


def _matrix(args: argparse.Namespace) -> tuple[bytes, bytes]:
    plan = _matrix_plan(args)
    inputs = _json_argument(args.inputs, dict, None)
    if args.describe:
        cases = expand_matrix(plan)
        value = {
            "cases": [{"case_id": item.case_id, "original_index": item.case_index,
                       "assignment": item.assignment} for item in cases],
            "matrix_plan_id": plan.plan_id,
        }
        data = _canonical(value)
    elif args.case:
        result = execute_matrix_case(plan, args.case, inputs=inputs)
        data = result.to_json_bytes()
    else:
        execution = execute_matrix(plan, inputs=inputs)
        data = canonical_inspection_bytes(inspect(execution))
    return data, _pretty(data)


def _batch(args: argparse.Namespace) -> tuple[bytes, bytes, CLIExitCode]:
    source_data = _read(args.source)
    try:
        raw = json.loads(_text(source_data), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (json.JSONDecodeError, ValueError):
        raise _CLIError("batch plan must be strict JSON", CLIExitCode.VALIDATION) from None
    if not isinstance(raw, Mapping) or not isinstance(raw.get("runs"), list):
        raise _CLIError("batch plan requires an ordered runs list", CLIExitCode.VALIDATION)
    allowed = {"runs", "fail_fast", "retained_result_bytes"}
    if not set(raw) <= allowed:
        raise _CLIError("batch plan contains unknown fields", CLIExitCode.VALIDATION)
    base = None if args.source == "-" else Path(args.source).parent
    requests = []
    for item in raw["runs"]:
        requests.append(_batch_request(item, base))
    plan = BatchPlan(
        tuple(requests), fail_fast=raw.get("fail_fast", False),
        retained_result_bytes=raw.get("retained_result_bytes", DEFAULT_RETAINED_RESULT_BYTES),
    )
    execution = execute_batch(plan, workers=args.workers, max_in_flight=args.max_in_flight)
    data = canonical_inspection_bytes(inspect(execution))
    failed = execution.envelope.manifest.failure_count != 0
    return data, _pretty(data), CLIExitCode.EXECUTION if failed else CLIExitCode.SUCCESS


def _batch_request(item: Any, base: Path | None) -> RunRequest:
    if not isinstance(item, Mapping):
        raise _CLIError("batch run must be an object", CLIExitCode.VALIDATION)
    allowed = {"id", "scenario", "root", "seed", "run_index", "locale", "inputs"}
    if set(item) - allowed or not {"id", "scenario", "seed"} <= set(item):
        raise _CLIError("batch run has missing or unknown fields", CLIExitCode.VALIDATION)
    source = item["scenario"]
    if not isinstance(source, str) or source == "-":
        raise _CLIError("batch scenario must be an explicit local file", CLIExitCode.SECURITY_OR_BOUND)
    path = Path(source)
    if not path.is_absolute():
        if base is None:
            raise _CLIError("stdin batch plans require absolute scenario paths", CLIExitCode.SECURITY_OR_BOUND)
        path = base / path
    root = item.get("root")
    if root is not None:
        root_path = Path(root)
        if not root_path.is_absolute():
            if base is None:
                raise _CLIError("stdin batch plans require absolute composition roots", CLIExitCode.SECURITY_OR_BOUND)
            root_path = (base / root_path).resolve()
        root = str(root_path)
    target, composed = _load_target(str(path), root)
    return RunRequest(
        item["id"], target, item["seed"], item.get("run_index", 0),
        item.get("locale", "C"), item.get("inputs", {}),
        execution_mode=ExecutionMode.COMPOSED if composed else ExecutionMode.DIRECT,
    )


def _bundle_at(root_value: str):
    root = _require_absolute_local(root_value, "evidence bundle root")
    return read_evidence_bundle(root / BUNDLE_INDEX_FILENAME, bundle_root=root)


def _bundle_summary(command: str, bundle: Any) -> dict[str, Any]:
    return {
        "bundle_id": bundle.bundle_id,
        "command": command,
        "entry_count": len(bundle.entries),
        "relationship_count": len(bundle.relationships),
        "schema": bundle.schema_version,
        "verified": True,
    }


def _export(args: argparse.Namespace) -> tuple[bytes, bytes]:
    bundle = _bundle_at(args.source)
    destination = _require_absolute_local(args.destination, "evidence destination")
    exported = export_evidence_bundle(
        bundle, source_root=Path(args.source), destination=destination,
    )
    value = _bundle_summary("export", exported)
    return _canonical(value), (
        f"exported evidence bundle {exported.bundle_id} "
        f"({len(exported.entries)} entries, {len(exported.relationships)} relationships)\n"
    ).encode("utf-8")


def _verify(args: argparse.Namespace) -> tuple[bytes, bytes]:
    bundle = _bundle_at(args.bundle)
    value = _bundle_summary("verify", bundle)
    return _canonical(value), (
        f"verified evidence bundle {bundle.bundle_id} "
        f"({len(bundle.entries)} entries, {len(bundle.relationships)} relationships)\n"
    ).encode("utf-8")


def _compatibility_fixtures(args: argparse.Namespace) -> tuple[bytes, bytes]:
    destination = _require_absolute_local(args.out, "compatibility fixture destination")
    exported = export_compatibility_fixtures(destination)
    value = {
        "command": "compatibility-fixtures export",
        "destination": str(exported),
        "schema": "scenario.compatibility-fixtures/1",
    }
    return _canonical(value), f"exported frozen compatibility fixtures to {exported}\n".encode()


def _migrate(args: argparse.Namespace) -> tuple[bytes, bytes]:
    _reject_remote(args.source)
    descriptor = ArtifactDescriptor(
        args.artifact_kind, args.schema_version, args.product_version, args.source_sha256,
    )
    plan = plan_migration(descriptor, args.target_contract)
    if plan.disposition is not MigrationDisposition.PLANNED:
        raise _CLIError("no supported lossless migration route", CLIExitCode.VALIDATION)
    transformations = ",".join(step.transformation_id for step in plan.steps)
    if args.dry_run:
        return canonical_migration_plan_bytes(plan), (
            f"planned lossless migration {plan.plan_id} ({transformations})\n"
        ).encode("utf-8")
    source = _require_absolute_local(args.source, "migration source")
    destination = _require_absolute_local(args.destination, "migration destination")
    result = execute_lossless_migration(
        plan, source_descriptor=descriptor, source_path=source,
        destination=destination,
    )
    return canonical_migration_result_bytes(result), (
        f"migrated losslessly {result.plan_id} -> {result.target_sha256} "
        f"({','.join(result.transformations)})\n"
    ).encode("utf-8")


def _canonical(value: Any) -> bytes:
    return json.dumps(
        normalize(value), ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _pretty(data: bytes) -> bytes:
    value = json.loads(data)
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _write(data: bytes) -> None:
    if len(data) > MAX_RENDERED_OUTPUT_BYTES:
        raise _CLIError("rendered output exceeds its byte bound", CLIExitCode.SECURITY_OR_BOUND)
    sys.stdout.buffer.write(data)
    if not data.endswith(b"\n"):
        sys.stdout.buffer.write(b"\n")


def _diagnostic(message: str) -> None:
    safe = " ".join(message.replace("\x00", "").split())[:MAX_DIAGNOSTIC_CHARS]
    sys.stderr.write(f"scenario: error: {safe}\n")


def _dsl_diagnostic(error: DSLError) -> HumanDiagnostic:
    diagnostic = getattr(error, "human_diagnostic", None)
    if not isinstance(diagnostic, HumanDiagnostic):
        diagnostic = HumanDiagnostic(
            "DSL_SEMANTIC_ERROR", "DSL_SEMANTIC", "scenario validation failed",
            remediation="correct the scenario declaration",
        )
    return diagnostic


def _scaffold_diagnostic(error: ScaffoldError) -> HumanDiagnostic:
    diagnostic = getattr(error, "human_diagnostic", None)
    if isinstance(diagnostic, HumanDiagnostic):
        return diagnostic
    return HumanDiagnostic(
        "SCAFFOLD_PROVIDER_FAILED", "SCAFFOLD_AUTHORING", "scaffold authoring failed",
        remediation="REVIEW_SCAFFOLD_REQUEST",
    )


def _replay_diagnostic(error: ReplayCompatibilityError) -> HumanDiagnostic:
    details: dict[str, str] = {}
    if error.artifact_contract is not None:
        details["artifact_contract"] = bounded_text(error.artifact_contract)
    if error.scenario_expected is not None:
        details["scenario_expected"] = bounded_text(error.scenario_expected)
    if error.scenario_received is not None:
        details["scenario_received"] = bounded_text(error.scenario_received)
    if error.missing:
        details["missing"] = bounded_text(",".join(error.missing))
    if error.migration is not None:
        details["migration"] = error.migration.value
    return HumanDiagnostic(
        error.reason_code, error.category, "replay artifact is incompatible",
        expected=None if error.expected is None else bounded_text(error.expected),
        received=None if error.received is None else bounded_text(error.received),
        remediation=error.remediation, details=details,
    )


def _render_replay_human(diagnostic: HumanDiagnostic) -> None:
    fields = [f"code={diagnostic.code}", f"category={diagnostic.category}"]
    details = diagnostic.details or {}
    if "artifact_contract" in details:
        fields.append(f"artifact_contract={details['artifact_contract']}")
    if diagnostic.expected is not None:
        fields.append(f"expected={diagnostic.expected}")
    if diagnostic.received is not None:
        fields.append(f"received={diagnostic.received}")
    for name in ("scenario_expected", "scenario_received", "missing", "migration"):
        if name in details:
            fields.append(f"{name}={details[name]}")
    fields.append(f"next_action={diagnostic.remediation}")
    _diagnostic("; ".join(fields))


def _path_reason(error: Exception) -> PathReason | None:
    """Classify existing path-security failures without replacing their checks."""
    if isinstance(error, _CLIError):
        return error.path_reason
    if isinstance(error, UnsupportedCompositionSourceError):
        return PathReason.PATH_REMOTE_FORBIDDEN
    if isinstance(error, CompositionRootEscapeError):
        return PathReason.PATH_OUTSIDE_ALLOWED_ROOT
    if isinstance(error, CompositionModuleNotFoundError):
        return PathReason.PATH_NOT_FOUND
    message = str(error).lower()
    if isinstance(error, CompositionPathError):
        if "absolute path" in message:
            return PathReason.PATH_NOT_ABSOLUTE
        if "root scenario path is invalid" in message:
            return PathReason.PATH_OUTSIDE_ALLOWED_ROOT
        if "does not exist" in message:
            return PathReason.PATH_NOT_FOUND
        return PathReason.PATH_UNSAFE
    if isinstance(error, EvidenceDestinationError):
        if "absolute path" in message:
            return PathReason.PATH_NOT_ABSOLUTE
        if "already exists" in message:
            return PathReason.DESTINATION_ALREADY_EXISTS
        if "parent" in message and ("does not exist" in message or "cannot be inspected" in message):
            return PathReason.DESTINATION_PARENT_MISSING
        if "invalid" in message or "must be a directory" in message or "symlink" in message:
            return PathReason.INVALID_DESTINATION
        return PathReason.DESTINATION_NOT_WRITABLE
    if isinstance(error, EvidenceFilesystemError):
        if "absolute path" in message:
            return PathReason.PATH_NOT_ABSOLUTE
        if "beneath the bundle root" in message:
            return PathReason.PATH_OUTSIDE_ALLOWED_ROOT
        if "does not exist" in message:
            return PathReason.PATH_NOT_FOUND
        return PathReason.PATH_UNSAFE
    return None


def _path_diagnostic(reason: PathReason, operation: str) -> HumanDiagnostic:
    actions = {
        PathReason.PATH_NOT_ABSOLUTE: "SUPPLY_ABSOLUTE_LOCAL_FILESYSTEM_PATH",
        PathReason.PATH_REMOTE_FORBIDDEN: "SUPPLY_LOCAL_FILESYSTEM_PATH",
        PathReason.PATH_OUTSIDE_ALLOWED_ROOT: "SUPPLY_PATH_WITHIN_ALLOWED_ROOT",
        PathReason.PATH_NOT_FOUND: "SUPPLY_EXISTING_LOCAL_PATH",
        PathReason.PATH_UNSAFE: "SUPPLY_SAFE_LOCAL_FILESYSTEM_PATH",
        PathReason.INVALID_DESTINATION: "SUPPLY_SAFE_ABSENT_DESTINATION",
        PathReason.DESTINATION_ALREADY_EXISTS: "SUPPLY_ABSENT_DESTINATION",
        PathReason.DESTINATION_PARENT_MISSING: "SUPPLY_DESTINATION_WITH_EXISTING_PARENT",
        PathReason.DESTINATION_NOT_WRITABLE: "SUPPLY_WRITABLE_DESTINATION_PARENT",
    }
    return HumanDiagnostic(
        reason.value, "FILESYSTEM_TRUST_BOUNDARY", "local filesystem path was rejected",
        remediation=actions[reason],
        details={"operation": bounded_text(operation), "path_kind": "local_filesystem"},
    )


def _render_path_human(diagnostic: HumanDiagnostic) -> None:
    details = diagnostic.details or {}
    _diagnostic(
        f"code={diagnostic.code}; category={diagnostic.category}; "
        f"operation={details['operation']}; path_kind={details['path_kind']}; "
        f"next_action={diagnostic.remediation}"
    )


def _emit_machine(diagnostic: HumanDiagnostic, code: CLIExitCode) -> None:
    sys.stderr.write(render_error_envelope(diagnostic, int(code)))


def _mapped(error: Exception) -> CLIExitCode:
    if isinstance(error, UnsupportedDSL2ExecutionError):
        return CLIExitCode.EXECUTION
    if isinstance(error, TraceViewError):
        return CLIExitCode.SECURITY_OR_BOUND if error.code in {"TRACE_INPUT_TOO_LARGE", "TRACE_OUTPUT_TOO_LARGE"} else CLIExitCode.VALIDATION
    if isinstance(error, (UnsupportedReplayContractError, ReplayCompatibilityError)):
        return CLIExitCode.REPLAY_COMPATIBILITY
    if isinstance(error, (CompositionBoundError, ArtifactBoundError, InspectionBoundError, DiffBoundError)):
        return CLIExitCode.SECURITY_OR_BOUND
    if isinstance(error, (EvidenceBoundError, EvidenceExportBoundError, EvidenceValidationBoundError,
                          EvidenceFilesystemError)):
        return CLIExitCode.SECURITY_OR_BOUND
    if isinstance(error, (EvidenceDestinationError, EvidencePublicationError)):
        return CLIExitCode.IO
    if isinstance(error, (EvidenceContractError, EvidenceIndexError, EvidenceIntegrityError, EvidenceSourceIntegrityError,
                          EvidenceValidationError, EvidenceMigrationError)):
        return CLIExitCode.VALIDATION
    if isinstance(error, (UnsupportedCompositionSourceError, CompositionPathError)):
        return CLIExitCode.SECURITY_OR_BOUND
    if isinstance(error, (DSLError, CompositionError, ArtifactReadError, SuiteSerializationError)):
        return CLIExitCode.VALIDATION
    if isinstance(error, ScaffoldError):
        return CLIExitCode.VALIDATION
    if isinstance(error, (MatrixError, BatchError, InspectionError, DiffError)):
        return CLIExitCode.VALIDATION
    if isinstance(error, ScenarioEngineError):
        return CLIExitCode.EXECUTION
    if isinstance(error, (TypeError, ValueError)):
        return CLIExitCode.VALIDATION
    return CLIExitCode.INTERNAL


def main(argv: Sequence[str] | None = None) -> int:
    """Run the shared CLI and return one frozen exit-family integer."""
    requested = tuple(sys.argv[1:] if argv is None else argv)
    json_mode = "--json" in requested
    try:
        args = _parser().parse_args(requested)
        handler = {
            "validate": _validate, "scaffold": _scaffold, "run": _run, "replay": _replay,
            "trace-view": _trace_view, "hash": _hash,
            "inspect": _inspect, "explain": _explain, "diff": _diff,
            "diff-definition": _diff_definition, "impact": _impact,
            "matrix": _matrix, "batch": _batch,
            "compatibility-fixtures": _compatibility_fixtures, "export": _export,
            "verify": _verify, "migrate": _migrate,
        }[args.command]
        outcome = handler(args)
        machine, human = outcome[0], outcome[1]
        code = outcome[2] if len(outcome) == 3 else CLIExitCode.SUCCESS
        _write(machine if args.json else human)
        return int(code)
    except _CLIError as error:
        reason = _path_reason(error)
        if reason is not None:
            diagnostic = _path_diagnostic(reason, getattr(locals().get("args"), "command", "cli"))
            if json_mode:
                _emit_machine(diagnostic, error.code)
            else:
                _render_path_human(diagnostic)
        else:
            diagnostic = HumanDiagnostic(
                "CLI_ERROR", "CLI_USAGE", bounded_text(str(error)),
                remediation="correct the command invocation",
            )
            if json_mode:
                _emit_machine(diagnostic, error.code)
            else:
                _diagnostic(str(error))
        return int(error.code)
    except Exception as error:
        code = _mapped(error)
        if isinstance(error, ReplayCompatibilityError):
            diagnostic = _replay_diagnostic(error)
            if json_mode:
                _emit_machine(diagnostic, code)
            else:
                _render_replay_human(diagnostic)
            return int(code)
        reason = _path_reason(error)
        if reason is not None:
            diagnostic = _path_diagnostic(reason, getattr(locals().get("args"), "command", "cli"))
            if json_mode:
                _emit_machine(diagnostic, code)
            else:
                _render_path_human(diagnostic)
            return int(code)
        if isinstance(error, DSLError):
            diagnostic = _dsl_diagnostic(error)
            if json_mode:
                _emit_machine(diagnostic, code)
            else:
                sys.stderr.write(render_human_diagnostic(diagnostic))
            return int(code)
        if isinstance(error, ScaffoldError):
            diagnostic = _scaffold_diagnostic(error)
            if json_mode:
                _emit_machine(diagnostic, code)
            else:
                sys.stderr.write(render_human_diagnostic(diagnostic))
            return int(code)
        if isinstance(error, TraceViewError):
            diagnostic = HumanDiagnostic(
                error.code, error.category, bounded_text(str(error)),
                remediation="SUPPLY_SUPPORTED_BOUNDED_LOCAL_ARTIFACT",
            )
            if json_mode:
                _emit_machine(diagnostic, code)
            else:
                sys.stderr.write(render_human_diagnostic(diagnostic))
            return int(code)
        if code is CLIExitCode.INTERNAL:
            message = "unexpected internal error"
        else:
            message = f"{type(error).__name__} occurred"
        diagnostic = HumanDiagnostic(
            "INTERNAL_ERROR" if code is CLIExitCode.INTERNAL else "COMMAND_ERROR",
            "INTERNAL" if code is CLIExitCode.INTERNAL else "COMMAND",
            message,
        )
        if json_mode:
            _emit_machine(diagnostic, code)
        else:
            _diagnostic(message)
        return int(code)
