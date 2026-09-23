from __future__ import annotations

from dataclasses import MISSING, fields
from datetime import datetime, timezone

import pytest

from scenario_engine import (
    canonical_scenario_bytes,
    compile_document,
    parse_yaml,
    run_scenario,
)
from scenario_engine.dsl.models import ScenarioDocument


def _document() -> ScenarioDocument:
    return ScenarioDocument(
        dsl_version=1,
        scenario_id="python-311-default",
        reference_clock_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        initial_state={},
        steps=(),
    )


def test_python311_mapping_defaults_use_fresh_immutable_factories():
    first = _document()
    second = _document()

    assert first.resources == {}
    assert first.resources is not second.resources
    with pytest.raises(TypeError):
        first.resources["unexpected"] = True

    resources_field = next(item for item in fields(ScenarioDocument) if item.name == "resources")
    assert resources_field.default is MISSING
    assert resources_field.default_factory is not MISSING


def test_repaired_default_preserves_canonical_scenario_and_result_bytes():
    source = """\
dsl_version: 1
scenario: python-311-default
clock:
  start: 2024-01-01T00:00:00Z
initial_state: {}
steps:
  - id: finish
    write: {}
    transition: null
"""
    parsed = parse_yaml(source)
    explicit = ScenarioDocument(
        dsl_version=parsed.dsl_version,
        scenario_id=parsed.scenario_id,
        reference_clock_start=parsed.reference_clock_start,
        initial_state=parsed.initial_state,
        steps=parsed.steps,
        resources={},
    )

    assert canonical_scenario_bytes(parsed) == canonical_scenario_bytes(explicit)
    assert run_scenario(compile_document(parsed), "seed").to_json_bytes() == run_scenario(
        compile_document(explicit), "seed"
    ).to_json_bytes()
