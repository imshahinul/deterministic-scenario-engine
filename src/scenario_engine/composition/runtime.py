"""Composition orchestration over the unchanged v1 execution authority."""

from __future__ import annotations

import hashlib

from scenario_engine.dsl import run_scenario
from scenario_engine.plugins import PluginRegistry
from scenario_engine.suite import (
    ArtifactReference,
    CompatibilityRecord,
    ExecutionContext,
    ExecutionReplaySupport,
    RunManifestEnvelope,
    SuiteManifest,
    canonical_suite_bytes,
)

from .models import ComposedExecution, ComposedSuite


def execute_composed_suite(
    suite: ComposedSuite,
    root_seed: str | int,
    run_index: int = 0,
    locale: str = "C",
    inputs=None,
    plugins: PluginRegistry | None = None,
) -> ComposedExecution:
    """Execute a resolved suite through the existing deterministic runtime."""
    if not isinstance(suite, ComposedSuite):
        raise TypeError("suite must be a ComposedSuite")
    result = run_scenario(
        suite.compiled, root_seed, run_index=run_index, locale=locale,
        inputs=inputs, plugins=plugins,
    )
    plugin_versions = {
        key.removeprefix("plugin:"): value
        for key, value in result.manifest.generator_versions.items()
        if key.startswith("plugin:")
    }
    run_manifest = RunManifestEnvelope(
        root_scenario_identity=suite.root_scenario_identity,
        execution_context=ExecutionContext(
            root_seed=result.manifest.root_seed,
            run_index=result.manifest.run_index,
            locale=result.manifest.locale,
            reference_clock_start=result.manifest.reference_clock_start,
        ),
        compatibility=CompatibilityRecord(
            execution_contract=f"scenario-engine/{result.manifest.engine_version}",
            execution_replay=ExecutionReplaySupport.SUPPORTED,
            plugin_versions=plugin_versions,
        ),
        child_manifest=result.manifest,
        suite_hash=suite.composed_hash,
    )
    run_bytes = canonical_suite_bytes(run_manifest)
    reference = ArtifactReference(
        kind="run_manifest",
        identity=f"{suite.root_scenario_identity}:{run_index}",
        sha256=hashlib.sha256(run_bytes).hexdigest(),
    )
    suite_manifest = SuiteManifest(
        root_scenario_identity=suite.root_scenario_identity,
        composed_hash=suite.composed_hash,
        composition_contract_version=suite.contract_version,
        module_hashes={item.alias: item.content_hash for item in suite.modules},
        child_runs=(reference,),
    )
    return ComposedExecution(suite, result, suite_manifest, run_manifest)
