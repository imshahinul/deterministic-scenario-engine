# Public Python API

This is the canonical top-level Phase 1.0 contract. Importable implementation
symbols not listed here are not implicitly promoted to top-level public API.

## Constants and value objects

- `ENGINE_VERSION` — engine compatibility version recorded in manifests; for
  the 1.0 release candidate it intentionally equals distribution version 1.0.0.
- `MISSING` — singleton semantic missing value, distinct from null.
- `LogicalID(value: str)` — deterministic logical identifier value; users
  normally receive it from `$id` generation.
- `ExecutionAddress(scenario_id: str, run_index: int = 0,
  subflow_invocations: tuple[int, ...] = (), repetition_indexes: tuple[int, ...]
  = (), step_id: str | None = None, semantic_path: tuple[str, ...] = ())` — users
  normally inspect plugin context addresses rather than constructing execution.
- `ScenarioResult(scenario_id: str, runner: ScenarioRunner,
  manifest: ReproducibilityManifest, resources: Any = None, provenance: Any =
  None)` — returned by execution; direct construction depends on nonpublic
  kernel objects and is not the normal user path.
- `ReproducibilityManifest(root_seed: str | int,
  scenario_canonical_hash: str, engine_version: str, dsl_version: int,
  input_resource_hashes: Mapping[str, str] = {}, domain_pack_versions:
  Mapping[str, str] = {}, generator_versions: Mapping[str, str] = {},
  rng_algorithm_version: str = "scenario-engine-addressed-v1",
  id_algorithm_version: str = "scenario-engine-id-v1", locale: str = "C",
  reference_clock_start: datetime | None = None, run_index: int = 0)` — normally
  received as `ScenarioResult.manifest`; construction is useful for persistence
  readers/tests only when every frozen field is preserved.
- `GeneratorPlugin(name: str, version: str, generate: PluginCallable)` — explicit
  deterministic generator definition.
- `PluginRegistry(plugins: Iterable[GeneratorPlugin] = ())` — immutable explicit
  registry.
- `PluginGenerationContext(rng: DeterministicRNG, clock: LogicalClock,
  ids: DeterministicIDProvider, address: ExecutionAddress)` — normally received
  by a plugin callable.

The named kernel types in annotations above are not thereby top-level exports.

## Parsing, compilation, execution, and replay

```python
parse_yaml(text: str) -> ScenarioDocument
parse_yaml_file(path: str | Path) -> ScenarioDocument
compile_document(document: ScenarioDocument, resources=None, plugins=None, state=None) -> CompiledScenario
run_scenario(scenario: CompiledScenario, root_seed, run_index=0, locale="C", inputs=None, plugins=None)
replay_scenario(yaml_text, manifest, *, inputs=None, plugins=None)
evaluate_scenario(scenario: CompiledScenario, root_seed, run_index=0, locale="C", inputs=None, raise_on_mismatch=False, plugins=None)
```

`parse_yaml_file()` reads UTF-8. `compile_document()` normally receives only a
parsed document; its other arguments support established integration/runtime
paths. `run_scenario()` returns `ScenarioResult`. `replay_scenario()` parses and
checks recorded compatibility before returning a replayed `ScenarioResult`.
`evaluate_scenario()` returns `OracleEvaluation` and optionally raises on an
oracle mismatch.

## Canonical scenario functions

```python
canonical_scenario_payload(scenario: str | ScenarioDocument | CompiledScenario) -> Mapping[str, Any]
canonical_scenario_bytes(scenario: str | ScenarioDocument | CompiledScenario) -> bytes
canonical_scenario_hash(scenario: str | ScenarioDocument | CompiledScenario) -> str
```

These normalize a YAML string, parsed document, or compiled scenario to the
canonical semantic scenario payload, bytes, or SHA-256 hash.

## Public error categories

All canonical errors derive from `ScenarioEngineError` and retain value-error
compatibility:

- `ScenarioEngineError`
- `DSLError`
- `DSLParseError`
- `DSLSchemaError`
- `DSLCompilationError`
- `ExpressionEvaluationError`
- `ResourceError`
- `ResourceValidationError`
- `ConstraintError`
- `ControlFlowError`
- `InvariantError`
- `FaultError`
- `OracleError`
- `ReplayCompatibilityError`
- `PluginError`

Catch the narrowest useful category. Stable submodule families include more
specific diagnostic classes without adding them to the canonical top level.

## Exact canonical top-level names

The set and order are:

```text
ENGINE_VERSION
MISSING
LogicalID
ExecutionAddress
ScenarioResult
ReproducibilityManifest
parse_yaml
parse_yaml_file
compile_document
run_scenario
replay_scenario
evaluate_scenario
canonical_scenario_payload
canonical_scenario_bytes
canonical_scenario_hash
GeneratorPlugin
PluginRegistry
PluginGenerationContext
ScenarioEngineError
DSLError
DSLParseError
DSLSchemaError
DSLCompilationError
ExpressionEvaluationError
ResourceError
ResourceValidationError
ConstraintError
ControlFlowError
InvariantError
FaultError
OracleError
ReplayCompatibilityError
PluginError
```

## Supported optional submodules

These are explicitly separate from the top-level contract:

- `scenario_engine.adapters.sqlalchemy`: `SqlAlchemyRowCommand`,
  `MaterializationReport`, `extract_row_commands`, `prepare_row_commands`,
  `command_fingerprint`, `materialize_result`, and its adapter errors; see
  [SQLAlchemy](sqlalchemy.md).
- `scenario_engine.integrations.hypothesis`: `ScenarioHypothesisCase`,
  `scenario_cases`, and `HypothesisIntegrationError`; see
  [Hypothesis](hypothesis.md).
- `scenario_engine.integrations.schemathesis`: `SchemathesisCaseBindings`,
  `BoundSchemathesisCase`, `bind_case`, `operation_cases`, and integration errors;
  see [Schemathesis](schemathesis.md).
- `scenario_engine.pytest_plugin`: pytest fixture/marker integration when the
  `pytest` extra is installed.
- `scenario_engine.reference_packs.ecommerce`: `ecommerce_registry()` reference
  factory; see [plugins](plugins.md).

Internal dataclass field layouts beyond frozen normalized result/manifest schemas
are not promised. See [compatibility](compatibility.md).
