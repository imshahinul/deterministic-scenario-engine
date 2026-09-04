"""Immutable semantic models for deterministic composed scenarios."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from types import MappingProxyType
from typing import Any, Mapping

from scenario_engine.dsl import CompiledScenario, ScenarioDocument
from scenario_engine.result import ScenarioResult
from scenario_engine.suite import RunManifestEnvelope, SuiteManifest
from scenario_engine.values import normalize

from .errors import CompositionSuiteContractError


COMPOSITION_CONTRACT_VERSION = "composition.modules/1"
MAX_MODULES = 64
MAX_ROOT_DOCUMENT_BYTES = 1 * 1024 * 1024
MAX_MODULE_DOCUMENT_BYTES = 1 * 1024 * 1024
MAX_AGGREGATE_INPUT_BYTES = 16 * 1024 * 1024
MAX_CANONICAL_COMPOSED_BYTES = 16 * 1024 * 1024

_ALIAS = re.compile(r"[a-z][a-z0-9_]*\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")


def valid_alias(value: Any) -> bool:
    return isinstance(value, str) and _ALIAS.fullmatch(value) is not None


def _freeze(value: Any) -> Any:
    normalize(value)
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(value[key]) for key in sorted(value)})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class ModuleIdentity:
    """A path-free alias/content identity and canonical declaration payload."""

    alias: str
    content_hash: str
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not valid_alias(self.alias):
            raise CompositionSuiteContractError("module alias has invalid shape")
        if not isinstance(self.content_hash, str) or _HASH.fullmatch(self.content_hash) is None:
            raise CompositionSuiteContractError("module content hash is not lowercase SHA-256")
        if not isinstance(self.payload, Mapping):
            raise CompositionSuiteContractError("module payload must be a mapping")
        object.__setattr__(self, "payload", _freeze(self.payload))


@dataclass(frozen=True, slots=True)
class ComposedSuite:
    """Resolved path-independent suite plus its executable DSL 1 scenario."""

    root_scenario_identity: str
    root_payload: Mapping[str, Any]
    modules: tuple[ModuleIdentity, ...]
    composed_hash: str
    document: ScenarioDocument
    compiled: CompiledScenario = field(compare=False, repr=False)
    manifest: SuiteManifest
    contract_version: str = COMPOSITION_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.root_scenario_identity, str) or not self.root_scenario_identity:
            raise CompositionSuiteContractError("root scenario identity must be non-empty")
        if self.contract_version != COMPOSITION_CONTRACT_VERSION:
            raise CompositionSuiteContractError("composition contract version mismatch")
        if not isinstance(self.composed_hash, str) or _HASH.fullmatch(self.composed_hash) is None:
            raise CompositionSuiteContractError("composed hash is not lowercase SHA-256")
        modules = tuple(self.modules)
        if not all(isinstance(item, ModuleIdentity) for item in modules):
            raise CompositionSuiteContractError("modules contain an invalid identity")
        aliases = [item.alias for item in modules]
        if aliases != sorted(aliases) or len(aliases) != len(set(aliases)):
            raise CompositionSuiteContractError("modules must be uniquely alias-sorted")
        if not isinstance(self.document, ScenarioDocument) or not isinstance(self.compiled, CompiledScenario):
            raise CompositionSuiteContractError("resolved DSL scenario has an invalid type")
        if not isinstance(self.manifest, SuiteManifest):
            raise CompositionSuiteContractError("suite manifest has an invalid type")
        object.__setattr__(self, "root_payload", _freeze(self.root_payload))
        object.__setattr__(self, "modules", modules)


@dataclass(frozen=True, slots=True)
class ComposedExecution:
    """Existing v1 result with additive suite/run identity envelopes."""

    suite: ComposedSuite
    result: ScenarioResult
    suite_manifest: SuiteManifest
    run_manifest: RunManifestEnvelope

    def __post_init__(self) -> None:
        if not isinstance(self.suite, ComposedSuite) or not isinstance(self.result, ScenarioResult):
            raise CompositionSuiteContractError("composed execution contains an invalid result")
        if not isinstance(self.suite_manifest, SuiteManifest) or not isinstance(self.run_manifest, RunManifestEnvelope):
            raise CompositionSuiteContractError("composed execution contains an invalid manifest")
