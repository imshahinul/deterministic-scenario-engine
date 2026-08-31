"""Normalized, byte-stable observable scenario results."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Mapping

from .manifest import ReproducibilityManifest
from .runner import ScenarioRunner
from .values import normalize


def _trace(runner: ScenarioRunner) -> list[Mapping[str, Any]]:
    return [{
        "address": record.address.canonical(),
        "artifacts": [[item_id, kind] for item_id, kind in record.emitted_artifacts],
        "faults_applied": list(record.faults_applied or ()),
        "patch": record.state_patch,
        "post": record.post_state_fingerprint,
        "pre": record.pre_state_fingerprint,
        "timestamp": record.logical_timestamp,
        "transition": record.transition_selected,
    } for record in runner.history.records]


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    scenario_id: str
    runner: ScenarioRunner = field(compare=False, repr=False)
    manifest: ReproducibilityManifest
    _normalized_snapshot: Mapping[str, Any] = field(init=False, compare=False, repr=False)

    def __post_init__(self) -> None:
        snapshot = normalize({
            "artifacts": [{
                "address": artifact.address.canonical(),
                "id": artifact.logical_id,
                "name": artifact.name,
                "type": artifact.artifact_type,
                "value": artifact.value,
            } for artifact in self.runner.artifacts],
            "clock": self.runner.clock.current,
            "history": _trace(self.runner),
            "manifest": self.manifest.normalized(),
            "next": self.runner.next_step,
            "scenario_id": self.scenario_id,
            "state": self.runner.state.to_dict(),
            "terminal_transition": self.runner.next_step,
        })
        object.__setattr__(self, "_normalized_snapshot", snapshot)

    @property
    def final_state(self) -> Mapping[str, Any]:
        return self.runner.state.to_dict()

    @property
    def history(self) -> Any:
        return self.runner.history

    @property
    def artifacts(self) -> tuple[Any, ...]:
        return tuple(self.runner.artifacts)

    @property
    def logical_clock(self) -> Any:
        return self.runner.clock.current

    @property
    def terminal_transition(self) -> str | None:
        return self.runner.next_step

    def normalized(self) -> Mapping[str, Any]:
        return json.loads(json.dumps(self._normalized_snapshot, ensure_ascii=False))

    def to_jsonable(self) -> Mapping[str, Any]:
        return self.normalized()

    def to_json(self) -> str:
        return json.dumps(
            self._normalized_snapshot,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    def to_json_bytes(self) -> bytes:
        return self.to_json().encode("utf-8")

    def trace(self) -> list[Mapping[str, Any]]:
        return self.normalized()["history"]
