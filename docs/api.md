# Public Python API

This is the canonical top-level Phase 1.0 contract, preserved unchanged by the
Phase 2 and Phase 3 freezes. Importable implementation symbols not listed here
are not implicitly promoted to top-level public API. Specialized APIs are public
through the explicit subpackages documented below, not package-root convenience
exports.

## Constants and value objects

- `ENGINE_VERSION` — engine compatibility version recorded in manifests; for
  current manifests it remains 1.0.0 independently of distribution version.
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

## Phase 2 public subpackages

The complete machine-frozen names are each subpackage's `__all__`; these import
paths are stable while helpers outside `__all__` are intentionally internal.

- `scenario_engine.suite` — versioned run/suite/matrix/batch manifests and
  bounded non-executing v1 result/manifest readers.
- `scenario_engine.composition` — `ComposedSuite`, `load_composed_suite()`,
  `execute_composed_suite()`, hashes, frozen bounds, and composition errors.
- `scenario_engine.matrix` — `MatrixDimension`, `MatrixPlan`, expansion,
  selection and execution with ordered Cartesian semantics, stable case IDs,
  and retained original Cartesian indexes.
- `scenario_engine.batch` — immutable `RunRequest`/`BatchPlan`, ordered
  `execute_batch()`/`stream_batch()` results, stable failures, and bounds.
- `scenario_engine.inspection` — immutable inspection/explanation documents,
  read-only normalization, canonical serializers, and default secret redaction.
- `scenario_engine.diff` — typed `SemanticDiff`/`DiffRecord` values using RFC
  6901 paths, deterministic `first`/`complete` modes and prefix truncation.
- `scenario_engine.cli` — `CLIExitCode` and `main`; command behavior is in the
  [Phase 2 public contract](phase2-public-contract.md#cli-contract).
- `scenario_engine.domain_packs` — immutable declarative `DomainPack` values,
  caller-created `DomainPackRegistry`, exact deterministic resolution, semantic
  identity, and declarative plugin requirements. There is no discovery, global
  registry, or pack dependency mechanism.
- `scenario_engine.oracle_assertions` — pure post-result structured assertion
  models, evaluation, serializers, outcomes, and bounds; evaluation never reruns
  or replays a scenario.

The schema/version constants and all exact export manifests are executable
contract tests. See the [complete Phase 2 contract](phase2-public-contract.md).

## Phase 3 evidence APIs

Phase 3 adds no package-root names. Its stable APIs are the names in `__all__`
of `scenario_engine.evidence` and `scenario_engine.reference_packs`; helpers in
their implementation modules are intentionally internal. Typical imports are:

```python
from scenario_engine.evidence import (
    ArtifactDescriptor,
    EvidenceBundle,
    EvidenceEntry,
    EvidenceProvenance,
    EvidenceRelationship,
    EvidenceType,
    compatibility_report,
    export_evidence_bundle,
    plan_migration,
    read_evidence_bundle,
)
from scenario_engine.reference_packs import (
    EcommerceEvidenceWorkflow,
    ecommerce_domain_pack,
    export_ecommerce_evidence,
)
```

The evidence subpackage exposes immutable bundle/entry/relationship/provenance
models and canonicalization; bounded local reading and atomic export; canonical
JSON/JSONL records; explicit adapter capability/publication/receipt contracts;
finite compatibility reports and metadata-only migration plans; six closed,
lossless executable wrapper routes; and deterministic fixture-directory export.
`scenario_engine.reference_packs` exposes the ecommerce demonstrator and its
existing registry factory, not a generic workflow framework. The exact public
names, errors, schemas, limits, and compatibility posture are normative in the
[Phase 3 public contract](phase3-public-contract.md).
