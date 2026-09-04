"""Thin, bounded CLI orchestration over accepted Scenario Engine APIs."""

from __future__ import annotations

import argparse
from enum import IntEnum
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping, Sequence

from scenario_engine.batch import (
    DEFAULT_RETAINED_RESULT_BYTES, BatchError, BatchPlan, ExecutionMode,
    RunRequest, execute_batch,
)
from scenario_engine.canonical import canonical_scenario_hash
from scenario_engine.composition import (
    ComposedSuite, CompositionBoundError, CompositionError,
    CompositionPathError, UnsupportedCompositionSourceError,
    execute_composed_suite, load_composed_suite,
)
from scenario_engine.diff import (
    DEFAULT_MAX_DIFF_RECORDS, DiffBoundError, DiffError, canonical_diff_bytes,
    render_diff_text, semantic_diff,
)
from scenario_engine.dsl import (
    DSLError, compile_document, parse_yaml, replay_scenario, run_scenario,
)
from scenario_engine.errors import ScenarioEngineError
from scenario_engine.inspection import (
    InspectionBoundError, InspectionError, canonical_explanation_bytes,
    canonical_inspection_bytes, explain_result, inspect,
)
from scenario_engine.manifest import ReplayCompatibilityError, ReproducibilityManifest
from scenario_engine.matrix import (
    MatrixDimension, MatrixError, MatrixPlan, execute_matrix,
    execute_matrix_case, expand_matrix,
)
from scenario_engine.suite import (
    ArtifactBoundError, ArtifactReadError, RunManifestEnvelope,
    SuiteSerializationError, UnsupportedReplayContractError,
    parse_suite_bytes, read_v1_manifest_bytes, read_v1_result_bytes,
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


class _CLIError(Exception):
    def __init__(self, message: str, code: CLIExitCode) -> None:
        super().__init__(message)
        self.code = code


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _CLIError("invalid command-line arguments", CLIExitCode.USAGE)


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="scenario", description="Deterministic Scenario Engine")
    parser.add_argument("--json", action="store_true", help="emit canonical JSON")
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    validate = commands.add_parser("validate", help="validate a scenario without execution")
    _source(validate)

    run = commands.add_parser("run", help="execute a scenario")
    _source(run)
    _execution(run)

    replay = commands.add_parser("replay", help="replay a supported recorded manifest")
    replay.add_argument("source", help="local manifest JSON path or - for stdin")
    replay.add_argument("--scenario", required=True, help="explicit local scenario YAML path")
    replay.add_argument("--inputs", help="bounded JSON object")

    hash_command = commands.add_parser("hash", help="print semantic scenario identity")
    _source(hash_command)

    inspect_command = commands.add_parser("inspect", help="inspect a recorded artifact")
    inspect_command.add_argument("source", help="local artifact JSON path or - for stdin")
    inspect_command.add_argument(
        "--kind", choices=("result", "manifest", "suite"), default="result",
        help="artifact contract",
    )

    explain = commands.add_parser("explain", help="explain a recorded result")
    explain.add_argument("source", help="local result JSON path or - for stdin")

    difference = commands.add_parser("diff", help="semantically compare two artifacts")
    difference.add_argument("left", help="first local artifact JSON path or -")
    difference.add_argument("right", help="second local artifact JSON path or -")
    difference.add_argument("--kind", choices=("result", "manifest", "suite"), default="result")
    difference.add_argument("--mode", choices=("first", "complete"), default="first")
    difference.add_argument("--max-records", type=int, default=DEFAULT_MAX_DIFF_RECORDS)

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
    return parser


def _source(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("source", help="explicit local scenario YAML path or - for stdin")
    parser.add_argument("--root", help="explicit composition root")


def _execution(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--seed", required=True, help="explicit root seed")
    parser.add_argument("--run-index", type=int, default=0, help="nonnegative run index")
    parser.add_argument("--locale", default="C", help="explicit locale coordinate")
    parser.add_argument("--inputs", help="bounded JSON object")


def _reject_remote(source: str) -> None:
    lowered = source.lower()
    if lowered.startswith(("http://", "https://")) or (_SCHEME.match(source) and source != "-"):
        raise _CLIError("remote and URI-like input sources are forbidden", CLIExitCode.SECURITY_OR_BOUND)


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
            if not path.is_file():
                raise _CLIError("input source must be a regular local file", CLIExitCode.IO)
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
        raise _CLIError("composition root must be explicit and absolute", CLIExitCode.SECURITY_OR_BOUND)
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


def _run(args: argparse.Namespace) -> tuple[bytes, bytes]:
    target, composed = _load_target(args.source, args.root)
    inputs = _json_argument(args.inputs, dict, None)
    if composed:
        result = execute_composed_suite(
            target, _seed(args.seed), run_index=args.run_index, locale=args.locale, inputs=inputs,
        ).result
    else:
        result = run_scenario(
            target, _seed(args.seed), run_index=args.run_index, locale=args.locale, inputs=inputs,
        )
    data = _result_output(result)
    return data, data


def _manifest(value: Mapping[str, Any]) -> ReproducibilityManifest:
    return ReproducibilityManifest(**dict(value))


def _replay(args: argparse.Namespace) -> tuple[bytes, bytes]:
    artifact = _read(args.source)
    scenario = _text(_read(args.scenario), "scenario")
    inputs = _json_argument(args.inputs, dict, None)
    try:
        suite_value = parse_suite_bytes(artifact)
    except SuiteSerializationError:
        suite_value = None
    if isinstance(suite_value, RunManifestEnvelope):
        suite_value.compatibility.require_execution_replay()
        if suite_value.child_manifest is None:
            raise UnsupportedReplayContractError(suite_value.compatibility.execution_contract, ())
        manifest = suite_value.child_manifest
    else:
        read = read_v1_manifest_bytes(artifact)
        read.require_execution_replay()
        manifest = _manifest(read.payload)
    result = replay_scenario(scenario, manifest, inputs=inputs)
    data = result.to_json_bytes()
    return data, data


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


def _mapped(error: Exception) -> CLIExitCode:
    if isinstance(error, (UnsupportedReplayContractError, ReplayCompatibilityError)):
        return CLIExitCode.REPLAY_COMPATIBILITY
    if isinstance(error, (CompositionBoundError, ArtifactBoundError, InspectionBoundError, DiffBoundError)):
        return CLIExitCode.SECURITY_OR_BOUND
    if isinstance(error, (UnsupportedCompositionSourceError, CompositionPathError)):
        return CLIExitCode.SECURITY_OR_BOUND
    if isinstance(error, (DSLError, CompositionError, ArtifactReadError, SuiteSerializationError)):
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
    try:
        args = _parser().parse_args(argv)
        handler = {
            "validate": _validate, "run": _run, "replay": _replay, "hash": _hash,
            "inspect": _inspect, "explain": _explain, "diff": _diff,
            "matrix": _matrix, "batch": _batch,
        }[args.command]
        outcome = handler(args)
        machine, human = outcome[0], outcome[1]
        code = outcome[2] if len(outcome) == 3 else CLIExitCode.SUCCESS
        _write(machine if args.json else human)
        return int(code)
    except _CLIError as error:
        _diagnostic(str(error))
        return int(error.code)
    except Exception as error:
        code = _mapped(error)
        if code is CLIExitCode.INTERNAL:
            message = "unexpected internal error"
        elif code is CLIExitCode.REPLAY_COMPATIBILITY:
            message = "execution replay is not supported for the recorded contract"
        else:
            message = f"{type(error).__name__} occurred"
        _diagnostic(message)
        return int(code)
