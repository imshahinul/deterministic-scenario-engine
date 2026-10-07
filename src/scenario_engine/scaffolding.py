"""Provider-neutral, author-time-only scenario scaffolding."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Protocol
import json
import re

from scenario_engine.diagnostics import HumanDiagnostic
from scenario_engine.dsl import DSLError, compile_document, parse_yaml
from scenario_engine.errors import ScenarioEngineError


SCAFFOLD_CONTRACT = "scenario.scaffold/1"
DEFAULT_SCAFFOLD_PROVIDER = "deterministic-template"
MAX_SCAFFOLD_STEPS = 32
MAX_SCAFFOLD_IDENTIFIER_CHARS = 128
MAX_SCAFFOLD_CLOCK_CHARS = 128
MAX_SCAFFOLD_OUTPUT_BYTES = 1 * 1024 * 1024
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class ScaffoldError(ScenarioEngineError, ValueError):
    """Base class for bounded authoring-provider failures."""

    diagnostic_code = "SCAFFOLD_PROVIDER_FAILED"

    def __init__(self, message: str, *, expected: str | None = None,
                 received: str | None = None, remediation: str | None = None) -> None:
        self.human_diagnostic = HumanDiagnostic(
            self.diagnostic_code, "SCAFFOLD_AUTHORING", message,
            expected=expected, received=received, remediation=remediation,
        )
        super().__init__(message)


class ScaffoldRequestInvalidError(ScaffoldError):
    diagnostic_code = "SCAFFOLD_REQUEST_INVALID"


class ScaffoldProviderNotFoundError(ScaffoldError):
    diagnostic_code = "SCAFFOLD_PROVIDER_NOT_FOUND"


class ScaffoldProviderFailedError(ScaffoldError):
    diagnostic_code = "SCAFFOLD_PROVIDER_FAILED"


class ScaffoldOutputInvalidError(ScaffoldError):
    diagnostic_code = "SCAFFOLD_OUTPUT_INVALID"


@dataclass(frozen=True, slots=True)
class ScaffoldRequest:
    """Bounded structured intent; strings are labels, not interpreted prose."""

    scenario_id: str
    step_ids: tuple[str, ...]
    reference_clock_start: str = "2026-01-01T00:00:00Z"

    def __post_init__(self) -> None:
        _require_identifier(self.scenario_id, "scenario_id")
        if not self.step_ids or len(self.step_ids) > MAX_SCAFFOLD_STEPS:
            raise ScaffoldRequestInvalidError(
                "scaffold request must contain between 1 and 32 steps",
                expected="1..32 step IDs", received="invalid step count",
                remediation="SUPPLY_BOUNDED_STRUCTURED_INTENT",
            )
        for step_id in self.step_ids:
            _require_identifier(step_id, "step_id")
        if len(set(self.step_ids)) != len(self.step_ids):
            raise ScaffoldRequestInvalidError(
                "scaffold step IDs must be unique", expected="unique step IDs",
                received="duplicate step ID", remediation="SUPPLY_UNIQUE_STEP_IDS",
            )
        if (not isinstance(self.reference_clock_start, str) or not self.reference_clock_start
                or len(self.reference_clock_start) > MAX_SCAFFOLD_CLOCK_CHARS):
            raise ScaffoldRequestInvalidError(
                "reference clock start must be a bounded ISO-8601 string",
                expected="1..128 character ISO-8601 string", received="invalid clock label",
                remediation="SUPPLY_VALID_REFERENCE_CLOCK_START",
            )


def _require_identifier(value: object, field: str) -> None:
    if (not isinstance(value, str) or len(value) > MAX_SCAFFOLD_IDENTIFIER_CHARS
            or _IDENTIFIER.fullmatch(value) is None):
        raise ScaffoldRequestInvalidError(
            f"{field} must be a bounded symbolic identifier",
            expected="1..128 characters: letters, digits, dot, underscore, or hyphen",
            received="invalid identifier", remediation="SUPPLY_BOUNDED_STRUCTURED_INTENT",
        )


@dataclass(frozen=True, slots=True)
class ScaffoldProposal:
    proposed_dsl: str
    provider: str
    provider_version: str


@dataclass(frozen=True, slots=True)
class ScaffoldResult:
    proposed_dsl: str
    provider: str
    provider_version: str
    validated: bool
    contract: str = SCAFFOLD_CONTRACT

    def to_jsonable(self) -> dict[str, object]:
        return {
            "contract": self.contract,
            "proposed_dsl": self.proposed_dsl,
            "provider": self.provider,
            "provider_version": self.provider_version,
            "validated": self.validated,
        }


class ScaffoldProvider(Protocol):
    provider_id: str
    provider_version: str

    def propose(self, request: ScaffoldRequest) -> ScaffoldProposal: ...


class DeterministicTemplateProvider:
    """Offline DSL 1 template provider with no runtime authority."""

    provider_id = DEFAULT_SCAFFOLD_PROVIDER
    provider_version = "1"

    def propose(self, request: ScaffoldRequest) -> ScaffoldProposal:
        lines = [
            "dsl_version: 1",
            f"scenario: {_scalar(request.scenario_id)}",
            "clock:",
            f"  start: {_scalar(request.reference_clock_start)}",
            "initial_state:",
            "  scaffold_complete: false",
            "steps:",
        ]
        for index, step_id in enumerate(request.step_ids):
            final = index == len(request.step_ids) - 1
            lines.extend((f"  - id: {_scalar(step_id)}",))
            if final:
                lines.extend(("    write:", "      scaffold_complete:", "        $literal: true"))
            transition = None if final else request.step_ids[index + 1]
            lines.append(f"    transition: {_scalar(transition)}")
        text = "\n".join(lines) + "\n"
        return ScaffoldProposal(text, self.provider_id, self.provider_version)


def _scalar(value: str | None) -> str:
    return "null" if value is None else json.dumps(value, ensure_ascii=False)


BUILTIN_SCAFFOLD_PROVIDERS: Mapping[str, ScaffoldProvider] = MappingProxyType({
    DEFAULT_SCAFFOLD_PROVIDER: DeterministicTemplateProvider(),
})


def scaffold_scenario(request: ScaffoldRequest, *, provider: str = DEFAULT_SCAFFOLD_PROVIDER,
                      providers: Mapping[str, ScaffoldProvider] | None = None) -> ScaffoldResult:
    """Create and ordinarily validate proposed DSL without executing it."""
    available = BUILTIN_SCAFFOLD_PROVIDERS if providers is None else providers
    selected = available.get(provider)
    if selected is None:
        raise ScaffoldProviderNotFoundError(
            "requested scaffold provider is not available", expected="registered provider ID",
            received="unknown provider", remediation="SELECT_AVAILABLE_SCAFFOLD_PROVIDER",
        )
    try:
        proposal = selected.propose(request)
    except ScaffoldError:
        raise
    except Exception:
        raise ScaffoldProviderFailedError(
            "scaffold provider failed without producing a proposal",
            remediation="RETRY_OR_SELECT_ANOTHER_SCAFFOLD_PROVIDER",
        ) from None
    try:
        proposed_dsl = proposal.proposed_dsl
        proposal_provider = proposal.provider
        proposal_version = proposal.provider_version
        selected_provider = selected.provider_id
        selected_version = selected.provider_version
        metadata_valid = all(
            isinstance(item, str) and 0 < len(item) <= MAX_SCAFFOLD_IDENTIFIER_CHARS
            and _IDENTIFIER.fullmatch(item) is not None
            for item in (proposal_provider, proposal_version, selected_provider, selected_version)
        )
        output_size = len(proposed_dsl.encode("utf-8")) if isinstance(proposed_dsl, str) else -1
    except (AttributeError, TypeError, UnicodeError):
        metadata_valid = False
        output_size = -1
    if (not metadata_valid or proposal_provider != selected_provider
            or proposal_version != selected_version or not isinstance(proposed_dsl, str)
            or output_size > MAX_SCAFFOLD_OUTPUT_BYTES):
        raise ScaffoldProviderFailedError(
            "scaffold provider returned an invalid bounded result",
            remediation="REPAIR_OR_SELECT_ANOTHER_SCAFFOLD_PROVIDER",
        )
    try:
        compile_document(parse_yaml(proposed_dsl))
    except DSLError:
        raise ScaffoldOutputInvalidError(
            "scaffold provider output failed ordinary DSE validation",
            expected="valid DSL 1 scenario", received="invalid proposed DSL",
            remediation="REVIEW_PROVIDER_OUTPUT_OR_SELECT_ANOTHER_PROVIDER",
        ) from None
    return ScaffoldResult(
        proposed_dsl, proposal_provider, proposal_version, True,
    )


__all__ = [
    "DEFAULT_SCAFFOLD_PROVIDER", "DeterministicTemplateProvider", "SCAFFOLD_CONTRACT",
    "ScaffoldError", "ScaffoldOutputInvalidError", "ScaffoldProposal", "ScaffoldProvider",
    "ScaffoldProviderFailedError", "ScaffoldProviderNotFoundError", "ScaffoldRequest",
    "ScaffoldRequestInvalidError", "ScaffoldResult", "scaffold_scenario",
]
