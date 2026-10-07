"""Bounded deterministic rendering of supported artifacts as offline HTML."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import html
import json
from typing import Any, Mapping, Sequence

from scenario_engine.inspection.redaction import redact_mapping, validate_redacted_keys
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


def render_trace_view(artifact: ArtifactReadModel | RunManifestEnvelope) -> bytes:
    """Render one validated artifact without execution or state reconstruction."""
    document = _document(artifact)
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
        "</style></head><body><header><h1>Deterministic Scenario Engine trace</h1>"
        f"<p>Read-only offline view · input SHA-256 <code>{digest}</code></p></header>{body}"
        "<section aria-label=\"embedded evidence\"><h2>Embedded bounded evidence</h2>"
        f"<pre id=\"scenario-evidence\">{embedded}</pre></section>"
        "<footer><p>Single-stream presentation. Actor/lane presentation space is reserved; "
        "actor/lane execution is not implemented.</p></footer></body></html>\n"
    ).encode("utf-8")
    if len(rendered) > TRACE_VIEW_MAX_OUTPUT_BYTES:
        raise TraceViewError("TRACE_OUTPUT_TOO_LARGE", "trace-view HTML exceeds its output byte bound")
    return rendered


def _document(artifact: ArtifactReadModel | RunManifestEnvelope) -> dict[str, Any]:
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
    raise TraceViewError("TRACE_INPUT_UNSUPPORTED", "artifact contract is unsupported")


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


def _source_bytes(artifact: ArtifactReadModel | RunManifestEnvelope) -> bytes:
    if isinstance(artifact, RunManifestEnvelope):
        return canonical_suite_bytes(artifact)
    return _canonical(normalize(artifact.payload))


def _sections(document: Mapping[str, Any]) -> list[str]:
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
