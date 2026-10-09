"""Bounded deterministic rendering of supported artifacts as offline HTML."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import html
import json
from typing import Any, Mapping, Sequence

from scenario_engine.engine2 import Engine2Result, canonical_result2_bytes
from scenario_engine.inspection.redaction import redact_mapping, validate_redacted_keys
from scenario_engine.schedule import ScheduleArtifact
from scenario_engine.suite import ArtifactOrigin, ArtifactReadModel, RunManifestEnvelope
from scenario_engine.suite.serialization import canonical_suite_bytes
from scenario_engine.values import normalize


TRACE_VIEW_CONTRACT = "scenario.trace-view/1"
TRACE_VIEW_RENDERER_VERSION = 1
TRACE_VIEW_MAX_INPUT_BYTES = 16 * 1024 * 1024
TRACE_VIEW_MAX_OUTPUT_BYTES = 128 * 1024 * 1024
TRACE_VIEW_MAX_EVENTS = 100_000
TRACE_VIEW_MAX_DEPTH = 64
TRACE_VIEW_MAX_VALUE_BYTES = 1 * 1024 * 1024


class TraceViewError(ValueError):
    """A stable bounded trace-view failure."""

    category = "TRACE_VIEW"

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def render_trace_view(
    artifact: ArtifactReadModel | RunManifestEnvelope | Engine2Result, *,
    schedule: ScheduleArtifact | None = None,
) -> bytes:
    """Render one validated artifact without execution or state reconstruction."""
    if schedule is not None and not isinstance(artifact, Engine2Result):
        raise TraceViewError("TRACE_SCHEDULE_UNSUPPORTED", "schedule context requires scenario.result/2")
    document = _document(artifact, schedule)
    payload = _canonical(document)
    digest = hashlib.sha256(_source_bytes(artifact)).hexdigest()
    sections = _sections(document)
    body = "".join(sections)
    embedded = html.escape(payload.decode("utf-8"), quote=True)
    rendered = (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; "
        "style-src 'unsafe-inline'; img-src 'none'; font-src 'none'; connect-src 'none'; "
        "media-src 'none'; object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'\">"
        "<meta name=\"scenario-trace-view-contract\" content=\"scenario.trace-view/1\">"
        "<title>DSE static trace view</title><style>"
        ":root{color-scheme:light dark;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}"
        "body{max-width:1100px;margin:2rem auto;padding:0 1rem;line-height:1.45}"
        "header,section{border:1px solid #8886;border-radius:.4rem;padding:1rem;margin:1rem 0}"
        "h1,h2,h3{font-family:system-ui,sans-serif}dl{display:grid;grid-template-columns:max-content 1fr;gap:.4rem 1rem}"
        "dt{font-weight:bold}dd{margin:0;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere}"
        ".event{border-left:.3rem solid #678;padding-left:1rem}.muted{opacity:.75}"
        ".lane{border-left:.3rem solid #876;padding-left:1rem}"
        "</style></head><body><header><h1>Deterministic Scenario Engine trace</h1>"
        f"<p>Read-only offline view · input SHA-256 <code>{digest}</code></p></header>{body}"
        "<section aria-label=\"embedded evidence\"><h2>Embedded bounded evidence</h2>"
        f"<pre id=\"scenario-evidence\">{embedded}</pre></section>"
        + ("<footer><p>Logical actor lanes are filtered views of one global committed history; "
           "they do not represent operating-system threads or simultaneous execution.</p></footer>"
           if isinstance(artifact, Engine2Result) else
           "<footer><p>Single-stream presentation. Actor/lane presentation space is reserved; "
           "actor/lane execution is not implemented.</p></footer>")
        + "</body></html>\n"
    ).encode("utf-8")
    if len(rendered) > TRACE_VIEW_MAX_OUTPUT_BYTES:
        raise TraceViewError("TRACE_OUTPUT_TOO_LARGE", "trace-view HTML exceeds its output byte bound")
    return rendered


def _document(
    artifact: ArtifactReadModel | RunManifestEnvelope | Engine2Result,
    schedule: ScheduleArtifact | None,
) -> dict[str, Any]:
    if isinstance(artifact, ArtifactReadModel):
        if artifact.origin is not ArtifactOrigin.V1_RESULT:
            raise TraceViewError("TRACE_INPUT_UNSUPPORTED", "artifact does not contain a supported trace result")
        payload = _bounded(redact_mapping(dict(artifact.payload), validate_redacted_keys(None)), 0)
        history = payload.get("history")
        if not isinstance(history, list):
            raise TraceViewError("TRACE_INPUT_UNSUPPORTED", "result history is unavailable")
        if len(history) > TRACE_VIEW_MAX_EVENTS:
            raise TraceViewError("TRACE_INPUT_TOO_LARGE", "result history exceeds the event bound")
        return {
            "contract": TRACE_VIEW_CONTRACT,
            "input_contract": "scenario.result/1",
            "renderer_version": TRACE_VIEW_RENDERER_VERSION,
            "presentation": {"actor_lane_reserved": True, "stream": "single"},
            "evidence": payload,
        }
    if isinstance(artifact, RunManifestEnvelope):
        payload = json.loads(canonical_suite_bytes(artifact))
        return {
            "contract": TRACE_VIEW_CONTRACT,
            "input_contract": artifact.schema_version,
            "renderer_version": TRACE_VIEW_RENDERER_VERSION,
            "presentation": {"actor_lane_reserved": True, "stream": "single"},
            "evidence": _bounded(redact_mapping(payload, validate_redacted_keys(None)), 0),
        }
    if isinstance(artifact, Engine2Result):
        _validate_schedule_linkage(artifact, schedule)
        if len(artifact.history) > TRACE_VIEW_MAX_EVENTS:
            raise TraceViewError("TRACE_INPUT_TOO_LARGE", "result history exceeds the event bound")
        payload = _bounded(redact_mapping(dict(artifact.payload()), validate_redacted_keys(None)), 0)
        schedule_payload = None if schedule is None else _bounded(
            redact_mapping(dict(schedule.payload()), validate_redacted_keys(None)), 0,
        )
        return {
            "contract": TRACE_VIEW_CONTRACT,
            "input_contract": artifact.contract,
            "renderer_version": TRACE_VIEW_RENDERER_VERSION,
            "presentation": {"actor_lane_reserved": False, "stream": "global-with-actor-filters"},
            "integrity": {
                "canonical_hashes": "verified",
                "exact_execution_replay": "not performed",
                "schedule_context": "available" if schedule else "unavailable",
                "structurally_accepted": True,
            },
            "evidence": payload,
            "schedule": schedule_payload,
        }
    raise TraceViewError("TRACE_INPUT_UNSUPPORTED", "artifact contract is unsupported")


def _validate_schedule_linkage(result: Engine2Result, schedule: ScheduleArtifact | None) -> None:
    if schedule is None:
        return
    manifest = result.manifest
    actor_names = tuple(item["actor"] for item in result.actors)
    failure = None if result.failure is None else result.failure.payload()
    schedule_failure = None if schedule.failure is None else schedule.failure.payload()
    checks = (
        (result.schedule_reference.schedule_hash, schedule.schedule_hash),
        (manifest.scenario_hash, schedule.scenario_hash),
        (actor_names, schedule.actors),
        (manifest.root_seed, schedule.execution.root_seed),
        (manifest.schedule_seed, schedule.schedule_seed),
        (dict(manifest.input_resource_hashes), dict(schedule.input_resource_hashes)),
        (manifest.run_index, schedule.run_index),
        (manifest.scheduler_contract, schedule.scheduler_contract),
        (manifest.dsl_version, schedule.execution.dsl_version),
        (manifest.engine_version, schedule.execution.engine_version),
        (manifest.reference_clock_start, schedule.execution.reference_clock_start),
        (dict(manifest.generator_versions), dict(schedule.execution.generator_versions)),
        (result.classification, schedule.classification),
        (failure, schedule_failure),
    )
    if any(expected != received for expected, received in checks):
        raise TraceViewError("TRACE_SCHEDULE_MISMATCH", "schedule does not match result evidence")
    committed = [record for record in schedule.records if record.outcome == "COMMITTED"]
    if ([record.committed_history_length for record in committed] != list(range(len(result.history))) or
            len(committed) != len(result.history)):
        raise TraceViewError("TRACE_SCHEDULE_MISMATCH", "schedule commit coordinates do not match result history")


def _bounded(value: Any, depth: int) -> Any:
    if depth > TRACE_VIEW_MAX_DEPTH:
        raise TraceViewError("TRACE_INPUT_TOO_LARGE", "artifact nesting exceeds the viewer depth bound")
    if isinstance(value, Mapping):
        return {str(key): _bounded(item, depth + 1) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_bounded(item, depth + 1) for item in value]
    normalized = normalize(value)
    if isinstance(normalized, str) and len(normalized.encode("utf-8")) > TRACE_VIEW_MAX_VALUE_BYTES:
        prefix = normalized.encode("utf-8")[:TRACE_VIEW_MAX_VALUE_BYTES].decode("utf-8", "ignore")
        return {"availability": "truncated", "prefix": prefix, "original_utf8_bytes": len(normalized.encode("utf-8"))}
    return normalized


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _source_bytes(artifact: ArtifactReadModel | RunManifestEnvelope | Engine2Result) -> bytes:
    if isinstance(artifact, RunManifestEnvelope):
        return canonical_suite_bytes(artifact)
    if isinstance(artifact, Engine2Result):
        return canonical_result2_bytes(artifact)
    return _canonical(normalize(artifact.payload))


def _sections(document: Mapping[str, Any]) -> list[str]:
    if document["input_contract"] == "scenario.result/2":
        return _actor_sections(document)
    evidence = document["evidence"]
    manifest = evidence.get("manifest") if isinstance(evidence, Mapping) else None
    if not isinstance(manifest, Mapping):
        manifest = evidence.get("child_manifest") if isinstance(evidence, Mapping) else None
    identity = evidence.get("scenario_id", evidence.get("root_scenario_identity", "not present in artifact"))
    metadata = {
        "scenario identity": identity,
        "input contract": document["input_contract"],
        "viewer contract": document["contract"],
        "engine version": _at(manifest, "engine_version"),
        "manifest version": _at(manifest, "engine_version"),
        "DSL version": _at(manifest, "dsl_version"),
        "execution seed": _at(manifest, "root_seed", _at(evidence.get("execution_context"), "root_seed")),
        "scenario hash": _at(manifest, "scenario_canonical_hash"),
    }
    result = ["<section><h2>Identity and versions</h2>" + _definition_list(metadata) + "</section>"]
    history = evidence.get("history") if isinstance(evidence, Mapping) else None
    if isinstance(history, Sequence) and not isinstance(history, (str, bytes)):
        events = []
        for index, event in enumerate(history):
            if not isinstance(event, Mapping):
                continue
            event_data = {
                "address": event.get("address", "not present in artifact"),
                "logical timestamp": event.get("timestamp", "not present in artifact"),
                "state before fingerprint": event.get("pre", "not present in artifact"),
                "observed state patch": event.get("patch", "not present in artifact"),
                "state after fingerprint": event.get("post", "not present in artifact"),
                "faults applied": event.get("faults_applied", "not present in artifact"),
                "emitted artifact references": event.get("artifacts", "not present in artifact"),
                "transition": event.get("transition", "not present in artifact"),
            }
            events.append(f"<article class=\"event\"><h3>Event {index + 1}</h3>{_definition_list(event_data)}</article>")
        result.append("<section><h2>Authoritative step timeline</h2>" + ("".join(events) or _missing()) + "</section>")
    else:
        result.append("<section><h2>Authoritative step timeline</h2>" + _missing() + "</section>")
    for title, key in (("Final observed state", "state"), ("Emitted artifacts", "artifacts"),
                       ("Execution provenance", "provenance")):
        if isinstance(evidence, Mapping) and key in evidence:
            result.append(f"<section><h2>{title}</h2>{_pre(evidence[key])}</section>")
    hashes = _public_hashes(evidence)
    if hashes:
        result.append("<section><h2>Provenance and hashes</h2>" + _definition_list(hashes) + "</section>")
    return result


def _actor_sections(document: Mapping[str, Any]) -> list[str]:
    evidence = document["evidence"]
    schedule = document.get("schedule")
    manifest = evidence["manifest"]
    selections = {
        record["committed_history_length"]: record for record in schedule["records"]
        if record["outcome"] == "COMMITTED"
    } if isinstance(schedule, Mapping) else {}
    metadata = {
        "scenario identity": evidence["scenario_id"], "input contract": document["input_contract"],
        "viewer contract": document["contract"], "engine version": manifest["engine_version"],
        "manifest version": manifest["contract"], "DSL version": manifest["dsl_version"],
        "execution seed": manifest["root_seed"], "scenario hash": manifest["scenario_hash"],
    }
    result = ["<section><h2>Identity and versions</h2>" + _definition_list(metadata) + "</section>"]
    integrity = document["integrity"]
    result.append("<section><h2>Evidence integrity</h2>" + _definition_list({
        "structurally accepted evidence": integrity["structurally_accepted"],
        "canonical hash verification": integrity["canonical_hashes"],
        "exact execution replay": integrity["exact_execution_replay"],
        "schedule selection context": integrity["schedule_context"],
    }) + "</section>")
    events = []
    for index, event in enumerate(evidence["history"]):
        selection = selections.get(index)
        data = {
            "global history index": index, "actor identity": event["actor"],
            "step semantic address": event["address"], "logical clock": event["timestamp"],
            "transition status": "COMMITTED", "transition": event["transition"],
            "shared-state change": event["patch"], "state before fingerprint": event["pre"],
            "state after fingerprint": event["post"], "artifact/emission references": event["artifacts"],
            "faults applied": event["faults_applied"],
            "selection ordinal": selection["selection_ordinal"] if selection else "unavailable",
        }
        events.append(f'<article class="event"><h3>Commit {index}</h3>{_definition_list(data)}</article>')
    result.append("<section><h2>Global committed-history timeline</h2>" + ("".join(events) or _missing()) + "</section>")
    failed = [record for record in schedule["records"] if record["outcome"] == "FAILED"] if isinstance(schedule, Mapping) else []
    lanes = []
    controls = {item["actor"]: item for item in evidence["actors"]}
    for actor in sorted(controls, key=str.encode):
        lane_events = []
        for index, event in enumerate(evidence["history"]):
            if event["actor"] == actor:
                lane_events.append(_definition_list({
                    "global history index": index, "step semantic address": event["address"],
                    "logical clock": event["timestamp"], "transition status": "COMMITTED",
                    "shared-state change": event["patch"],
                }))
        attempts = [_selection_details(record) for record in failed if record["selected_actor"] == actor]
        control = controls[actor]
        lanes.append(f'<article class="lane"><h3>{html.escape(actor, quote=True)}</h3>' + _definition_list({
            "canonical actor identity": actor, "next step": control["next_step"],
            "terminal": control["terminal"], "committed transition count": len(lane_events),
        }) + "".join(lane_events) + "".join(attempts) + "</article>")
    result.append("<section><h2>Actor lanes</h2>" + "".join(lanes) + "</section>")
    if isinstance(schedule, Mapping):
        context = [_selection_details(record) for record in schedule["records"]]
        result.append("<section><h2>Authoritative scheduler-selection context</h2>" + "".join(context) + "</section>")
    else:
        result.append('<section><h2>Authoritative scheduler-selection context</h2>'
                      '<p class="muted">unavailable — no schedule evidence supplied; no ready sets or ordinals inferred</p></section>')
    result.append("<section><h2>Terminal outcome</h2>" + _definition_list({
        "classification": evidence["classification"], "failure": evidence["failure"],
        "final logical clock": evidence["final_logical_clock"],
    }) + "</section>")
    for title, key in (("Final observed state", "final_state"), ("Emitted artifacts", "artifacts"),
                       ("Execution provenance", "provenance")):
        result.append(f"<section><h2>{title}</h2>{_pre(evidence[key])}</section>")
    result.append("<section><h2>Provenance and hashes</h2>" + _definition_list(_public_hashes(evidence)) + "</section>")
    return result


def _selection_details(record: Mapping[str, Any]) -> str:
    return '<article class="event"><h3>Selection context</h3>' + _definition_list({
        "selection ordinal": record["selection_ordinal"], "canonical ready-actor set": record["ready_actors"],
        "selected actor": record["selected_actor"], "scheduler identity": record["scheduler_digest"],
        "preselection committed-history length": record["committed_history_length"],
        "preselection logical clock": record["logical_clock"], "selection outcome": record["outcome"],
    }) + "</article>"


def _public_hashes(value: Any, prefix: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {}
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            if "hash" in str(key).casefold() and not isinstance(item, (Mapping, list)):
                result[name] = item
            elif isinstance(item, Mapping):
                result.update(_public_hashes(item, name))
    return result


def _at(value: Any, key: str, default: Any = "not present in artifact") -> Any:
    return value.get(key, default) if isinstance(value, Mapping) else default


def _definition_list(items: Mapping[str, Any]) -> str:
    return "<dl>" + "".join(
        f"<dt>{html.escape(str(key))}</dt><dd>{_inline(value)}</dd>" for key, value in items.items()
    ) + "</dl>"


def _inline(value: Any) -> str:
    if isinstance(value, (Mapping, list, tuple)):
        return _pre(value)
    return f"<code>{html.escape(str(value), quote=True)}</code>"


def _pre(value: Any) -> str:
    text = json.dumps(normalize(value), ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2)
    return f"<pre>{html.escape(text, quote=True)}</pre>"


def _missing() -> str:
    return '<p class="muted">not present in artifact</p>'
