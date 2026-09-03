# Phase 2 Product Scope and Architecture Freeze

Status: frozen by checkpoint 2.0A. This document authorizes design direction only. It does not authorize Phase 2 implementation.

The product thesis is **generate test scenarios, not just test records**. The Phase 2 direction is to compose, generate, inspect, diff, and replay entire deterministic scenario suites without weakening the published v1 contract.

## Baseline and Immutable V1

The immutable source baseline is commit `ee29f52f714e84f17e1048ce24192fcf1c69345a`, tree `2a61915d578dcb1c4ec94049350a24d2cabdf721`, and annotated tag `1.0.0` peeled to that commit. The distribution is `deterministic-scenario-engine==1.0.0`, import package `scenario_engine`, under Apache-2.0. Its published wheel SHA-256 is `4a5dfe8666fdf82233ad2fecd1aa54a190291bf731a3929faca26047b5eab511`; its sdist SHA-256 is `3264bbbb1956ff183c01cd85f379fe1a9afdf31d9375be7f95c003aff1a1800e`.

The v1 DSL, top-level API, error families, deterministic addressing, RNG and ID algorithms, canonical semantic values and JSON bytes, result and manifest schemas, resource/input hashes, exact-version replay checks, plugin behavior, package metadata, and three published result hashes remain frozen. Phase 2 extensions must preserve v1 behavior when no new feature is used. Existing v1 results must retain byte identity under the v1 artifact; a future release must never claim compatible execution replay unless its complete compatibility tuple is supported deliberately.

No Phase 2 semantic coordinate may depend on an absolute machine path, directory enumeration, unordered-container iteration, ambient locale, environment variable, wall clock, global random stream, network response, worker scheduling, or process history.

## Architecture Inventory

The status column uses exactly the authorized classifications. “Public” means supported top-level or documented adapter/integration behavior; “internal” means implementation detail even when importable by module path.

| Item | Classification | Location and status | Basis and Phase 2 consequence | Stable dependencies |
|---|---|---|---|---|
| parser | FROZEN_V1_CONTRACT | `src/scenario_engine/dsl/parser.py`; public through `parse_yaml`/`parse_yaml_file` | Safe YAML and strict DSL 1 grammar are contract-tested. Additive syntax may extend it, but valid v1 meaning and rejection safety cannot be reinterpreted. | semantic values, DSL errors, models |
| compiler | INTERNAL_EXTENSION_POINT | `src/scenario_engine/dsl/compiler.py`; top-level entry public, internals private | Compilation is the proper static-resolution boundary. Composition should resolve to compiled library models, while existing documents compile identically. | parser models, expressions, runner specs, control validation |
| runtime | FROZEN_V1_CONTRACT | `src/scenario_engine/dsl/runtime.py`; public run/evaluate/replay functions | Execution and exact replay determine golden bytes. New suite APIs orchestrate this engine rather than duplicating it. | compiler, runner, manifest, resources, plugins, oracle |
| execution address | FROZEN_V1_CONTRACT | `src/scenario_engine/address.py`; `ExecutionAddress` is public | Address-derived isolation is central to RNG/ID stability. New matrix identity must map deterministically to an explicit run index without changing v1 address serialization. | scenario ID, run index, subflow/repeat/step paths |
| RNG | SHOULD_NOT_CHANGE | `src/scenario_engine/rng.py`; internal | Versioned addressed SHA-256 generation is frozen behavior. Batch members get independent addressed streams; no shared stream is allowed. | root seed, execution address, RNG version |
| LogicalID | FROZEN_V1_CONTRACT | `src/scenario_engine/ids.py`; `LogicalID` public, provider internal | Normalization and deterministic identity are public result semantics. Existing algorithm/version stay unchanged. | root seed, address, ID version, canonical values |
| state | SHOULD_NOT_CHANGE | `src/scenario_engine/state.py`; internal | In-memory atomic semantic state is a protected design boundary. Suite features operate above it and exporters remain downstream. | normalize/freeze semantics, runner commits |
| history | FROZEN_V1_CONTRACT | `src/scenario_engine/history.py`, `src/scenario_engine/result.py`; observable public result | Ordered committed history and trace shape are result contracts and primary inspection data. Add new observations outside the v1 snapshot rather than altering v1 records. | execution address, state fingerprints, clock, artifacts |
| canonicalization | FROZEN_V1_CONTRACT | `src/scenario_engine/values.py`, `src/scenario_engine/canonical.py`; public scenario APIs and result bytes | Hashes, replay, equality, JSON, Decimal/datetime/MISSING encodings depend on exact behavior. Composition needs a new suite/module envelope without changing single-file v1 payloads. | parser semantic model, sorted mappings, UTF-8 JSON, SHA-256 |
| ScenarioResult | FROZEN_V1_CONTRACT | `src/scenario_engine/result.py`; public | Exact normalized keys and bytes are contract-tested. Matrix/batch metadata belongs in new wrapper records, not retrofitted into v1 results. | runner snapshot, manifest, normalize, provenance |
| ReproducibilityManifest | FROZEN_V1_CONTRACT | `src/scenario_engine/manifest.py`; public | Field names, order, normalization, validation, and exact engine compatibility are frozen. Composition/matrix/batch require a versioned suite manifest envelope rather than changing this dataclass. | engine/DSL/RNG/ID/plugin versions, resource hashes, clock/run context |
| replay | FROZEN_V1_CONTRACT | `replay_scenario` in `src/scenario_engine/dsl/runtime.py`; public | v1 requires exact compatibility and rejects active domain packs. Future suite replay is a distinct library API and must reject unsupported v1 execution explicitly. | parser/compiler, canonical hash, manifest tuple, explicit inputs/plugins |
| resources | FROZEN_V1_CONTRACT | `src/scenario_engine/resources.py`; public behavior, internal resolved type | Ordered dependency resolution, explicit inputs, immutable snapshots, and hashes are tested. Parameters remain a suite-level assignment feeding explicit inputs; imports do not create hidden lookup paths. | canonical values, input maps, validators/constraints |
| expressions | FROZEN_V1_CONTRACT | `src/scenario_engine/expressions.py`; DSL behavior and some module APIs | Typed arithmetic, lookup, ordering, derivation, and deterministic errors are compatibility-sensitive. New assertion selectors may consume normalized data but do not expand expression authority casually. | Decimal context, semantic equality, state/resource/scope namespaces |
| validators | FROZEN_V1_CONTRACT | `src/scenario_engine/validation.py`, parser/compiler; DSL public | Resource shape/type checks own input validity, not outcome assertions. Their current order and errors remain stable. | resolved resources, semantic types |
| constraints | FROZEN_V1_CONTRACT | validation plus runtime; DSL public | Pre-execution resource/business preconditions and violations already have oracle/provenance meaning. They must not become post-result assertions. | expressions, resources, faults, oracle |
| control flow | FROZEN_V1_CONTRACT | `src/scenario_engine/control_flow.py`, compiler/runtime; DSL public | Nonrecursive subflows, ordered first-match branches, bounded repeats, and addresses are frozen. Imported subflows are namespaced declarations resolved before this layer. | compiler graph checks, scopes, addresses, repeat limits |
| invariants | FROZEN_V1_CONTRACT | `src/scenario_engine/invariants.py`; DSL public | Atomic per-step candidate-state checks own transition safety. Final/history assertions belong to oracle expectations, not invariants. | runner candidate commit, expressions, provenance |
| faults | FROZEN_V1_CONTRACT | `src/scenario_engine/faults.py`; DSL public | Explicit deterministic fault selection/application and expectation contribution are tested. Inspection reads recorded provenance; no hidden trace hook is added. | addresses, state/resources, invariants/oracle |
| oracle | PHASE2_EXTENSION_CANDIDATE | `src/scenario_engine/oracle.py` and runtime; DSL/public evaluation | Existing expected constraint/invariant violations are narrow. A bounded additive expectation vocabulary can cover final state and committed records in the same oracle layer. | ScenarioResult observations, semantic comparison, provenance, replay |
| provenance | FROZEN_V1_CONTRACT | `src/scenario_engine/provenance.py`; observable result/evaluation data | Ordered deterministic records already explain faults/checks/oracle. New suite resolution records should be immutable structured data outside hidden mutable tracing. | addresses, stable identifiers, normalized details |
| plugins | FROZEN_V1_CONTRACT | `src/scenario_engine/plugins.py`; public explicit registry | Trusted, explicit, versioned generator algorithms have no discovery/global registry. Composition and packs may aggregate explicit registries but cannot auto-load code. | deterministic context, manifest generator versions, semantic values |
| JSON adapter | INTERNAL_EXTENSION_POINT | `src/scenario_engine/adapters/json_file.py`; documented submodule API | Atomic downstream single-result export is the pattern for new exporters. Existing overwrite behavior remains; suite exporters consume wrapper results. | ScenarioResult JSON bytes, filesystem caller path |
| SQLAlchemy adapter | SHOULD_NOT_CHANGE | `src/scenario_engine/adapters/sqlalchemy.py`; documented optional API | Transactional post-result materialization is deliberately outside state/execution. It gains no matrix/batch semantics in Phase 2. | committed artifacts, explicit table bindings, SQLAlchemy transaction |
| pytest integration | INTERNAL_EXTENSION_POINT | `src/scenario_engine/pytest_plugin.py`; packaged entry point and documented fixture | Thin harness over public APIs is the model for CLI/CI. It must not become a separate engine or implicit discovery system. | parser/compiler/run/replay, optional dependency boundary |
| Hypothesis integration | INTERNAL_EXTENSION_POINT | `src/scenario_engine/integrations/hypothesis.py`; documented optional API | It already models independently replayable explicit run indexes/inputs. Matrix/batch abstractions may be composed with it later without changing draw semantics. | explicit strategies, run API, manifest |
| Schemathesis integration | SHOULD_NOT_CHANGE | `src/scenario_engine/integrations/schemathesis.py`; documented optional API | Local case binding only; automatic HTTP execution is a protected non-goal. Phase 2 CLI does not absorb network execution. | ScenarioResult, explicit bindings, Hypothesis/Schemathesis |
| reference/domain packs | PHASE2_EXTENSION_CANDIDATE | `src/scenario_engine/reference_packs/ecommerce.py`; explicit plugin registry; `domain_pack_versions` reserved-empty | Ecommerce is a reference plugin pack, not yet a domain-pack contract. A declarative explicit bundle can activate the reserved concept without changing plugin semantics. | explicit registry, pack identity/version, manifest envelope, trust boundary |
| public API | FROZEN_V1_CONTRACT | `src/scenario_engine/__init__.py`; exact `__all__` | Existing exports and errors are exact. Phase 2 favors new submodules; any additive top-level exports require a deliberate public-contract checkpoint. | import laziness, error root, packaging |
| packaging | FROZEN_V1_CONTRACT | `pyproject.toml`, `MANIFEST.in`, `_version.py`; public distribution | v1 identity, dependencies, pytest entry point, and version remain unchanged now. Future CLI entry point is an intentional package change only in implementation. | setuptools metadata, optional dependency isolation, license |
| documentation | PHASE2_EXTENSION_CANDIDATE | `README.md`, `docs/`; public | Normative v1 documentation is frozen; this document becomes the Phase 2 design authority. Future docs must distinguish old and new contracts. | implemented behavior, local-link validation |
| examples | SHOULD_NOT_CHANGE | `examples/`; public canonical examples | Current examples enforce golden behavior and remain byte-stable. New examples are added only alongside implemented features, never as placeholders. | parser/runtime, documentation tests, goldens |

## CLI Architecture

The distribution will add the console entry point `scenario = scenario_engine.cli:main`. A single shared application owns argument parsing, input decoding, rendering, and exception translation; command handlers invoke public library capabilities. The hierarchy is frozen as `scenario validate`, `run`, `replay`, `hash`, `inspect`, `explain`, and `diff`. `matrix` and `batch` are separate commands because matrix expands one declarative suite while batch executes an explicit heterogeneous run plan; neither is an alias for `run`.

One positional path is accepted, with `-` meaning stdin. Commands needing two documents use two positional sources, each independently allowing `-` only when at most one stdin stream is required. Relative composition paths are legal only when the root source is a file and an explicit `--root` is supplied or defaults to that file's parent; composed stdin requires explicit root. There is no environment search path.

Human output is the default and is concise, stable in section/order but not a canonical hash input. `--json` emits one canonical UTF-8 JSON value plus one LF to stdout; JSON schemas are versioned library serialization contracts. Successful payloads go only to stdout. Diagnostics go only to stderr, redact supplied values/paths unless verbosity explicitly requests safe details, and never include tracebacks by default. Deterministic commands produce byte-identical JSON for identical explicit inputs; progress, timing, host paths, colors, and worker completion order are excluded from machine output.

Exit families are: `0` success/equal; `1` valid comparison with differences or oracle mismatch; `2` CLI usage/input-source error; `3` parse/schema/compile/validation error; `4` execution/constraint/invariant/oracle failure; `5` replay compatibility rejection; `6` security/bound violation; `7` I/O/export error; `8` unexpected internal error. The CLI maps the library error hierarchy deterministically and never changes business semantics. CI uses `--json`, explicit roots/seeds/inputs, bounded expansion, and captured manifests/results. `replay` validates recorded contracts before execution. `inspect` renders structured observations; `explain` renders causal records; `diff` renders the library semantic diff. Command names map to cohesive library operations, not necessarily one top-level function each.

## Deterministic Multi-File Composition

The single mechanism is named **composition**, expressed by a root-level ordered mapping:

```yaml
composition:
  modules:
    checkout: modules/checkout.yaml
    catalog: modules/catalog.yaml
```

Imported files are **modules**; there are no `include` or `import` aliases. A module is DSL 1 YAML with `dsl_version`, `module`, and declaration sections (`resources`, `validators`, `constraints`, `subflows`, `invariants`, `faults`, and reusable oracle fragments where supported), but no executable root scenario, clock, initial state, steps, or nested composition. The root remains the only executable scenario and root identity is its `scenario` value. Logical module identity is the explicit alias, an ASCII identifier matching `[a-z][a-z0-9_]*`; physical filenames are never semantic identities.

The graph is a depth-one root-to-module DAG in Phase 2: modules cannot compose other modules. This intentionally eliminates transitive lookup and cycles; any module composition key is a schema error. The ordered YAML mapping is accepted for authorship, but resolution order is sorted by alias and therefore source mapping order has no semantics. Duplicate alias keys are rejected by the YAML parser. Duplicate canonical content under distinct aliases is allowed and remains distinct because alias is identity. Aliases namespace every imported declaration as `alias.name`; imported declarations are private except through that qualified name. Root unqualified declarations remain root-local. Any duplicate fully qualified declaration or collision with an explicitly dotted root declaration is a compile error; no shadowing, wildcard visibility, or implicit merge exists. Imported resources may refer to declarations in their own alias or explicit other aliases, and dependency resolution remains sorted and cycle-checked. Root/subflow calls use qualified names. Plugin names remain their existing globally namespaced identifiers; modules only declare requirements. Domain packs are explicit compilation inputs, never file imports.

The caller supplies an allowed filesystem root. Each module spelling must use `/`, be nonempty relative POSIX syntax, contain no empty, `.` or `..` segment, no backslash, drive prefix, leading slash, NUL, URI scheme, or network URL. Resolution joins the spelling beneath the allowed root, performs component-wise `lstat`, rejects every symlink, requires a regular file, resolves both root and candidate, and verifies containment. The same policy applies on every platform; paths are case-sensitive semantic spellings even on case-insensitive filesystems, and aliases—not paths—are coordinates. Case-fold-colliding spellings are rejected for portability. Absolute paths, symlink escapes, environment-derived paths, implicit current-directory search, dynamic imports, URI schemes, network retrieval, and remote composition are forbidden.

Each module has SHA-256 over its canonical semantic declaration payload. The composed scenario hash is SHA-256 over a versioned canonical envelope containing the unchanged canonical root scenario payload and the alias-sorted list of `{alias, content_hash, payload}`; no physical path is included. A new `SuiteManifest` records composition schema version, root scenario identity, composed hash, and alias-to-content-hash mapping, alongside the unchanged per-run v1 `ReproducibilityManifest`. Replay requires the caller to supply local root/module bytes and rejects any hash/identity mismatch before execution. This yields cross-machine reproduction independent of path layout. Limits are 64 modules, depth 1, 1 MiB per YAML file, and 16 MiB canonical composed payload.

## Parameters and Scenario Matrices

Parameters are suite-owned named explicit values. They are not resources: an assignment is transformed deterministically into the existing runtime `inputs` mapping, and resource declarations remain the only bridge from inputs into a scenario. The root seed, run index, locale, and reference clock are execution context, not parameters or dimensions. The scenario's clock remains DSL-owned.

The root may add a `matrix` section containing an ordered list of dimensions, each with a unique ASCII name and a nonempty ordered `values` sequence. Dimension declaration order is semantic; value list order is semantic; mappings/sets/filesystem enumeration are forbidden as dimension sources. Expansion is lexicographic odometer order with the last dimension changing fastest. It is the Cartesian product followed by ordered pure filters expressed in the restricted expression model over the complete parameter assignment. A filter retains only exact boolean true and cannot access state, time, environment, resources, plugins, or randomness.

`MatrixCase` stores `case_index`, ordered assignment, and `case_id`. The ID is lowercase SHA-256 of a versioned canonical assignment envelope including the composed scenario hash; duplicate canonical assignments are rejected, not coalesced. No dimensions means one empty-assignment case. Any dimension with zero values is invalid, so a declared matrix can produce zero cases only through filters; zero cases is valid for inspection but `matrix run` exits as no-work unless explicitly allowed. Maximum dimensions are 16, values per dimension 1,000, pre-filter Cartesian cardinality 100,000, and executable retained cases 10,000; bounds are checked with overflow-safe multiplication before materialization.

For execution, `run_index` equals `case_index` in the unfiltered Cartesian expansion, preserving stable identity if a filter removes another case. Root seed is identical across cases; addressed RNG isolation through run index makes each case independent. Seed derivation is forbidden. Matrix assignment, original Cartesian index, case ID, bounds/version, root seed, locale, input hashes, composition identity, and each child manifest participate in a new matrix bundle manifest. The unchanged single-scenario hash excludes matrix declarations; the suite hash includes canonical matrix declarations. One case can be reproduced from suite bytes, root seed, and case ID with its recorded original index. Replay of one case validates that identity and child manifest; replay of a matrix validates the suite manifest and returns results sorted by original case index.

## Deterministic Batch Execution

The library-first model is `BatchPlan`, an immutable ordered sequence of `RunRequest` records, executed by `execute_batch` into `BatchResult`. A request contains explicit run ID, resolved scenario/suite reference, root seed, run index, locale, inputs/parameter case, plugins/domain packs supplied by the caller, and execution mode. Run IDs are unique nonempty portable ASCII labels and are the batch coordinate; request order determines result order only, not random generation.

Every request invokes the same single-run/matrix library APIs with its own seed and run index. There is no shared RNG, ID provider, state, resource cache with mutable semantics, or sequential seed derivation. Reordering, omitting, adding, or parallelizing requests cannot alter any individual outcome. Results are emitted in plan order regardless of worker completion. Each `BatchItemResult` is a tagged success with result/manifest or failure with stable error family/code/safe message; tracebacks and exception objects are not serialized.

Default behavior is continue-on-error. `fail_fast=True` stops scheduling after the first failure in plan order, cancels only not-yet-started work, and records deterministic `NOT_RUN` entries for every omitted request. Because concurrency can make “already started” timing nondeterministic, fail-fast requires one worker; parallel fail-fast is rejected. Aggregation preserves all item statuses and summary counts. Each successful member is independently replayable. A batch bundle manifest records plan schema, canonical request identities/hashes, ordered child manifest hashes, statuses, and plan hash; it is not an execution-state store.

Bounds are 10,000 requests, maximum 64 workers, and an explicit aggregate retained-result byte budget defaulting to 256 MiB. The executor supports an ordered sink/iterator mode so completed results can be buffered only until their preceding sequence positions are emitted. Exceeding request/result bounds yields a deterministic bound error. Worker count and completion times never appear in semantic output.

## Inspect and Explain

Inspection is a library model separated from rendering. `inspect_result`, `inspect_manifest`, and suite equivalents produce immutable, versioned `InspectionDocument` sections. `explain_result` produces ordered `ExplanationRecord` values with kind, stable path/address, subject ID, outcome, and normalized details. CLI human/JSON renderers consume these values only.

The models expose ScenarioResult schema/hash, manifest tuple, final state, history, artifacts, trace, provenance, resource/input hashes, root seed, run index, locale, reference clock, engine/RNG/ID/generator/plugin/domain-pack versions, logical timestamps, transitions, fault applications, invariant/constraint failures, oracle evaluation, and generated-value addresses where recorded. Suite records add composition module identities/hashes/resolution order, matrix case/index/assignment, batch run identity/status, and child manifest links. Branch and repeat decisions not present in v1 records are inferred only where unambiguous from committed addresses/history; the model must label unavailable evidence rather than invent it. Replay rejection is represented from structured compatibility fields and stable errors.

No hidden mutable tracing is introduced. Phase 2 may add explicit immutable suite-level resolution/expansion records before execution, but must not change v1 result bytes. Secret-prone input values are omitted by default; only hashes are shown unless the caller explicitly provides and requests values.

## Structured Diff

The library defines `SemanticDiff`, containing comparison kind, equality, truncation metadata, and an ordered tuple of `DiffRecord`. A record has stable JSON Pointer path (RFC 6901 escaping), operation (`add`, `remove`, `replace`, or `type`), left/right presence flags, left/right semantic types, and normalized values subject to redaction. Presence flags distinguish MISSING from JSON null; semantic MISSING itself uses the existing `{"$missing":true}` encoding.

Inputs are normalized typed result, manifest, inspection, or suite-manifest models—not raw text. Mappings compare by Unicode key and records are emitted in path order. Sequences compare by index with no heuristic moves; removal/addition preserves index paths. Type differences are differences even when host-language equality says otherwise (therefore boolean differs from integer). Decimal compares by normalized engine semantic representation, preserving decimal type and scale as encoded. Datetimes compare after existing UTC normalization. Ordered history/artifacts/trace remain sequences. Unordered version/hash maps are normalized mappings.

Supported sections include scenario/composed hash, manifest, state, history, artifacts, trace, provenance, input/resource hashes, root seed, run index, locale, reference clock, engine/generator/plugin/domain-pack versions, composition identity, and matrix/batch identity. `mode="first"` returns the first stable record. `mode="complete"` defaults to 10,000 records and requires a caller maximum no greater than 100,000; on overflow it returns the deterministic prefix plus `truncated=true` and omitted count when known. Canonical JSON uses versioned schemas, sorted object keys, typed values, and no host paths. Human rendering is downstream and is never the comparison model.

## Oracle and Assertion Expansion

Oracle/assertion expansion is classified **SHOULD_HAVE_PHASE2**. The existing layers remain distinct: validators validate resource shape/type; constraints enforce pre-execution resource/business conditions; invariants protect every candidate state transition; oracle expectations judge observed execution outcomes.

Phase 2 adds assertion families to the existing oracle layer, not a new assertion engine: final-state path comparison/presence; history and artifact count; ordered subsequence; occurrence count of a typed predicate over normalized records; transition occurrence/order; and logical-time comparison. History assertions also cover committed branch/repeat effects only through stable recorded fields. “Artifact assertions” select normalized artifact records. Assertions use stable IDs, restricted pure selectors/comparators, explicit MISSING, and bounded scans; they cannot call Python, plugins, network, filesystem, clock, or randomness.

DSL 1 gains an additive `oracle.assertions` ordered list. Existing valid oracle syntax retains meaning and bytes when no new syntax is used. Reports add assertion observations only in a future evaluation wrapper/schema; v1 `ScenarioResult` is unchanged. Replay reevaluates assertions from the reproduced deterministic result and verifies oracle-definition hashes through the suite/scenario hash. Count, occurrence, ordering, transition, and logical-time assertions are operators in this one family, not separate abstractions. Compatibility risk is moderate because parser/canonical/oracle/error contracts change additively; the feature follows result inspection and diff foundations.

## Domain Packs

A domain pack is an explicitly registered, immutable, versioned bundle of declarative assets: namespaced resource templates, validators, constraints, oracle fragments, documentation metadata, and an optional explicit `PluginRegistry` supplied by trusted Python packaging. It differs from a plugin: a plugin is one generator algorithm callable; a pack composes declarations and may reference a set of plugins but cannot itself execute, access I/O, or create a registry implicitly.

Pack identity uses the plugin-style lowercase dotted namespace and an exact nonempty version. The caller constructs/registers `DomainPack` objects into an immutable `DomainPackRegistry`; scenarios declare exact `pack@version` requirements and qualified asset references. No entry-point loading, package scan, automatic discovery, global registry, dynamic YAML import, or network retrieval exists. Duplicate identities or conflicting versions fail before compilation. Pack assets join composition under a reserved `pack:<identity>` namespace; root/modules cannot shadow them.

Activated pack identities/versions and canonical asset hashes are recorded in the suite manifest and copied into each new-run compatibility envelope. The reserved v1 `domain_pack_versions` field remains empty for v1 execution; it is not silently activated because v1 replay explicitly rejects it. Future pack-aware replay requires explicit trusted registry, exact version, and asset hash. Distribution is ordinary separately installed Python packages or engine-shipped reference modules imported explicitly by application code. Packs and plugins are trusted, unsandboxed code boundaries; declarative assets still pass the safe parser. The public API is initially a new `scenario_engine.domain_packs` submodule, not an automatic top-level export.

## Reference Pack Strategy

Retain ecommerce and deepen it to demonstrate explicit domain-pack registration, composed catalog/checkout/fulfillment modules, parameterized regional/customer cases, order-lifecycle batch runs, oracle lifecycle assertions, inspection, replay, and semantic diff. Add one deep **payments/order-lifecycle** reference pack only if it exercises materially different fault, transition-order, Decimal, idempotency, and replay/diff behavior. Do not add SaaS, user, inventory-only, or API packs in Phase 2. Reference packs are **OPTIONAL_PHASE2** and are the first content feature deferred when core foundations need schedule protection.

## Export Adapters

Export adapters are **OPTIONAL_PHASE2** and downstream from `ScenarioResult`, `MatrixResult`, or `BatchResult`. Supported candidates are canonical multi-result JSON, JSONL, fixture directories, and manifest bundles. CSV is deferred because nested typed values force a lossy/ambiguous schema unless a later explicit flattening contract is designed.

JSON/multi-result/bundle typed values use existing normalization: MISSING as `{"$missing":true}`, Decimal as `{"$decimal":"..."}`, datetime as UTC `{"$datetime":"...Z"}`, duration/LogicalID per existing normalization, sorted object fields, and ordered result sequences. JSONL contains one canonical compact object plus LF per ordered result. Fixture filenames are zero-padded sequence plus a lowercase SHA-256 stable ID, never scenario text or host paths. Bundle layout is `bundle.json`, `manifests/<id>.json`, and `results/<id>.json`; the root index records every content hash and relationship. Writes reject existing destinations by default; explicit `overwrite=True` uses atomic replacement. Exporters execute nothing, resolve no state, and never become replay/state stores.

## CI and Developer Workflow

Generic workflows use library APIs or the CLI: validate all explicit roots; hash suite definitions; execute matrix/batch with explicit seed and limits; preserve canonical results/manifests/bundle as artifacts; replay selected or all members; semantic-diff against approved artifacts; and emit JSON diagnostics on failure. CI compares semantic hashes/diffs, not terminal text. Failure records include stable run/case IDs, error family, relevant addresses/paths, and redacted deterministic details.

GitHub Actions configuration remains documentation/examples. No CI-provider environment variables, annotations, artifact API, status API, or secret mechanism enters core semantics. Provider wrappers may map the generic exit families externally.

## Performance and Scale Targets

Security/safety bounds are hard deterministic validation limits; performance targets are measured goals and never change output semantics.

| Area | Safety bound | Baseline target on one CPython 3.11+ process |
|---|---:|---|
| root steps | 10,000 | 1,000 simple committed steps in under 1 s |
| resources | 10,000 declarations / 16 MiB normalized | 1,000-node DAG resolution in under 250 ms |
| composition | 64 modules, depth 1, 1 MiB/file, 16 MiB canonical | 32 modules / 8 MiB validate+hash under 2 s |
| repeat | existing per-repeat maximum remains authoritative; aggregate executed steps 100,000 | 10,000 repeated simple steps under 5 s |
| matrix | 16 dimensions, 1,000 values/dimension, 100,000 prefilter, 10,000 retained | expand/hash 10,000 cases under 1 s excluding runs |
| batch | 10,000 requests, 64 workers | 1,000 trivial runs with deterministic ordered sink under 30 s single worker |
| history | 100,000 records/run | canonicalize 10,000 records under 2 s |
| artifacts | 100,000/run and explicit 256 MiB aggregate budget | 10,000 small artifacts under 2 s serialization |
| trace/provenance | combined 100,000 records/run / 64 MiB | inspect 10,000 records under 1 s |
| canonical serialization | 256 MiB input/output | 16 MiB under 2 s and under 3x payload peak memory |
| diff | default 10,000; hard 100,000 records | first diff under 250 ms; 10,000 diffs under 2 s for 16 MiB inputs |

Benchmark fixtures cover linear steps, deep semantic values, wide resource DAG, maximum legal composition, filtered matrix, heterogeneous batch failures, artifact-heavy results, provenance-heavy oracle evaluation, equal canonicalization, first difference, and bounded complete difference. Repeat × matrix × batch aggregate work is checked before execution against an explicit run/step budget. Optimization may stream and cache immutable content hashes, but cannot change order, bytes, error precedence, or addressing.

## Version, DSL, and API Strategy

The eventual release strategy is **2.0.0**. Although valid v1 DSL remains accepted unchanged, suite composition/matrix manifests, CLI machine schemas, diff models, domain-pack activation, and replay policy create a materially larger public contract. Keeping this as 1.x would understate result/manifest ecosystem and replay compatibility impact. No package version changes in 2.0A.

DSL version remains **1**. Composition and matrix are additive root syntax with unambiguous absence defaults, and oracle assertions are additive. Existing valid DSL 1 cannot be reinterpreted, its canonical payload/result remains identical when new keys are absent, and unknown future forms still fail. A DSL version increment is required only if valid DSL 1 meaning or canonical semantics must change.

Existing top-level exports stay supported. Phase 2 first exposes composition, suite, batch, inspection, diff, and domain-pack types through explicit new submodules to preserve import laziness. A later API freeze may add a deliberately small set of top-level exports. New errors inherit `ScenarioEngineError` and stable category families. V1 `ScenarioResult` and `ReproducibilityManifest` schemas and canonical JSON do not change; new versioned wrapper schemas carry composition, matrix, batch, diff, and pack metadata.

## V1 to V2 Replay Posture

Choose policy **A**: explicitly reject execution replay when compatibility is not guaranteed. Phase 2 will parse/read v1 manifest JSON into a versioned read model, inspect v1 results/manifests, diff two v1 artifacts, and diff v1 against Phase 2 artifacts through normalized inspection models. These operations do not execute scenarios and do not promise byte reproduction.

Phase 2 does not preserve a complete hidden v1 executor and does not promise a compatibility executor. Direct execution replay of a manifest whose recorded engine version is `1.0.0` is rejected before execution by `ReplayCompatibilityError` (or additive subclass `UnsupportedReplayContractError`) with stable code `replay.engine_version_unsupported`, recorded version `1.0.0`, and supported execution contract(s), without a traceback or migration claim. Users needing exact v1 execution install the frozen, hash-verified v1 artifact. If implementation later proves unchanged algorithms satisfy complete compatibility, enabling v1 execution replay requires a separately reviewed explicit compatibility checkpoint; this freeze does not promise it.

## Security Guardrails

- Reject `..`, `.`, empty path components, absolute/drive/UNC paths, backslashes, URI schemes, NUL, symlinks at every component, nonregular files, root escape after resolution, and portability case-fold collisions. Require an explicit filesystem root; never use environment/PATH/home/current-directory searches implicitly.
- Forbid network URLs, remote composition, dynamic imports, YAML tags/aliases/merges, arbitrary Python from YAML, and unsafe deserialization. Composition reads bounded local UTF-8 files only.
- Preserve no automatic plugin/domain-pack discovery, no entry-point auto-loading (the pytest integration entry point is not plugin discovery), no global registries, and no dynamic YAML imports. Registration is explicit and immutable.
- Bound files/modules/depth, aggregate semantic bytes, resource DAG, steps, existing repeats, matrix pre/post-filter cardinality, batch count/workers, aggregate repeat×matrix×batch work, history/artifacts/provenance, retained bytes, serialization, and complete diff records before allocation or execution where practical.
- Keep state in memory and engine-owned; no database-backed state, ORM-owned state, raw SQL DSL, recursive subflows, unbounded loops, automatic Schemathesis HTTP execution, hidden network, wall clock, randomness, or environmental state.
- Plugins and Python-packaged domain packs are trusted and unsandboxed. Validate outputs and versions but never claim sandboxing. Declarative pack data remains safe-loaded and hashed.
- Machine diagnostics omit input values, environment, host paths, tracebacks, chained exception text, tokens, and headers by default. Stable error categories expose only bounded safe context. Explicit verbose rendering still redacts configured keys.
- Export destinations use caller paths, no semantic path coordinates, reject overwrite by default, avoid path interpolation from untrusted IDs, and write atomically.
- Reading/inspection/diff of older artifacts never triggers code loading, plugin invocation, network access, or scenario execution.
- Indefinite incompatible cross-major replay is not promised. Determinism and bounded failure outrank throughput.

## Feature Dependency Graph

Canonical textual graph (an arrow means “must precede”):

```text
V1 contract preservation -> Suite model/schema foundation
Suite model/schema foundation -> Composition -> Matrix -> Batch
Suite model/schema foundation -> InspectExplain -> StructuredDiff
InspectExplain -> OracleExpansion
Composition + explicit registry model + suite manifest -> DomainPacks
Composition + Matrix + Batch + InspectExplain -> CLI completion
CLI + replay + StructuredDiff -> CIDeveloperWorkflow
Composition + Matrix + Batch + DomainPacks + OracleExpansion -> ReferencePacks
Matrix + Batch + suite manifests -> ExportAdapters
all MUST_HAVE implementations -> PerformanceScale -> API/docs freeze -> RC -> acceptance -> publication
```

The true foundation is a versioned suite/run wrapper and manifest schema that preserves v1 objects, followed by secure composition. Matrix depends on composed suite identity; batch depends on stable single/matrix run identities. Inspect/explain can proceed in parallel after the wrapper schema, followed by diff. Domain packs are blocked by composition namespace and manifest decisions. CLI parsing can start early, but command completion is blocked by library capabilities. Export and CI are low-risk downstream work. Oracle expansion and reference content are deferrable. The likely critical path is suite schema → composition/security → matrix/address mapping → batch/bundles → CLI/replay integration → hardening/contracts/RC.

## Scope Classification

| Feature | Classification | Rationale | Dependencies |
|---|---|---|---|
| CLI | MUST_HAVE_PHASE2 | Provides one coherent end-to-end product surface while remaining library orchestration. | library APIs, all core result schemas |
| Composition | MUST_HAVE_PHASE2 | Enables deterministic scenario suites and is the central new product capability. | suite schema, parser/compiler, security model |
| Matrix | MUST_HAVE_PHASE2 | Turns explicit parameters into deterministic scenario-case suites. | composition identity, inputs/resources, addressing |
| Batch | MUST_HAVE_PHASE2 | Executes complete heterogeneous suites without order-dependent outcomes. | stable run/matrix identities, bundle schema |
| InspectExplain | MUST_HAVE_PHASE2 | Makes deterministic records operable and supplies structured diagnostics. | result/manifest read models, suite records |
| StructuredDiff | MUST_HAVE_PHASE2 | Gives semantic change detection needed for replay and CI workflows. | inspection/normalization models |
| OracleExpansion | SHOULD_HAVE_PHASE2 | Materially strengthens scenario truth but core suite generation remains useful without it. | inspect/result selectors, bounded assertion model |
| DomainPacks | MUST_HAVE_PHASE2 | Activates reusable explicit domain semantics with a boundary distinct from plugins. | composition namespace, explicit registries, suite manifest |
| ReferencePacks | OPTIONAL_PHASE2 | Deep examples prove cohesion but do not define the core architecture. | core features; domain packs/oracle for deepest value |
| ExportAdapters | OPTIONAL_PHASE2 | Useful downstream portability; canonical JSON already provides a base. | matrix/batch results and bundle manifests |
| CIDeveloperWorkflow | SHOULD_HAVE_PHASE2 | Generic documented workflow makes CLI/diff/replay materially useful without provider semantics. | CLI, replay, diff, exports optional |
| PerformanceScale | SHOULD_HAVE_PHASE2 | Bounds and benchmarks are release integrity; optimization beyond targets is deferrable. | completed must-have paths |

## Final Phase 2 Product Definition

Phase 2 adds a deterministic suite layer that v1 does not have: a developer can securely compose namespaced local scenario modules, expand explicit parameter matrices, execute independent ordered batches, record/replay exact suite cases, inspect causal deterministic evidence, and semantically diff results/manifests through one library-first CLI, while explicitly registering reusable domain packs. End to end, a developer validates a suite, hashes it, runs all or one reproducible case locally or in CI, preserves canonical bundles, explains a failure, verifies replay compatibility, and obtains a typed bounded diff without creating a second execution engine or changing v1 semantics.

## Implementation Roadmap

No checkpoint below is authorized by this document; each requires separate authorization.

| Checkpoint | Objective and bounded scope | Explicit non-goals | Predecessor / acceptance gate | Public/API/DSL and migration/replay |
|---|---|---|---|---|
| 2.0A — Product Scope + Architecture Freeze | This docs-only decision artifact and v1 evidence. | Runtime, tests, package/version/release changes. | Exact v1 baseline; document and regression validation. | No changes. |
| 2.1 — Suite Models + Read Contracts | Versioned run/suite/matrix/batch manifest envelopes, bounded read-only v1 artifact models, error families. | Composition execution, CLI commands, v1 executor. | 2.0A; canonical schemas/round trips and unchanged v1 bytes. | New submodule APIs possible; no DSL; define read/replay rejection. |
| 2.2 — Secure Deterministic Composition | One module syntax, resolver, namespaces, canonical composed hash, filesystem guardrails. | Nested/remote imports, discovery, execution redesign. | 2.1; traversal/symlink/cross-machine and hash tests. | Additive DSL 1 and APIs; suite replay metadata. |
| 2.3 — Parameters + Matrix | Parameter assignments, deterministic bounded expansion/filtering, stable case IDs/indexes, single-case replay. | Dynamic/environment dimensions, distributed scheduler. | 2.2; ordering/cardinality/address-isolation tests. | Additive DSL 1/APIs; matrix bundle migration is versioned only. |
| 2.4 — Deterministic Batch | Immutable plans/results, errors, ordered serial/parallel execution, bundles and streaming sink. | Queue service, remote workers, shared RNG, parallel fail-fast. | 2.3; worker/reorder independence and memory-bound gates. | New submodule API/schema; child replay links. |
| 2.5 — Inspect + Explain | Immutable inspection/explanation models for v1/new results, manifests, suites, failures. | Hidden tracing, terminal renderer as model. | 2.1 and suite records through 2.4; evidence completeness/redaction tests. | New APIs/schemas; read-only v1 compatibility. |
| 2.6 — Structured Semantic Diff | Typed bounded JSON-Pointer diffs and human renderer library hook. | Raw text as model, heuristic sequence moves. | 2.5; typed/MISSING/order/bound cross-version tests. | New APIs/schemas; v1-v1 and v1-new reading only. |
| 2.7 — CLI Product Surface | Console entry and validate/run/matrix/batch/replay/hash/inspect/explain/diff, streams, exits, JSON. | Any duplicate execution semantics, provider-specific CI. | 2.2–2.6; fresh CLI end-to-end and byte-stable machine output. | CLI/public packaging changes; no DSL beyond predecessors; replay rejection exposed. |
| 2.8 — Domain-Pack Foundation | Explicit pack/registry/assets/version/hash/manifest integration. | Discovery, auto-load, dynamic YAML, untrusted sandbox claim. | 2.2 and 2.1; exact registration/replay/trust tests. | New submodule and additive declarations; v1 reserved field unchanged. |
| 2.9 — Oracle Assertions | Bounded final/history/artifact/count/order/occurrence/transition/time oracle operators. | New assertion layer or arbitrary query language. | 2.5; deterministic reports/replay and existing-oracle compatibility. | Additive DSL 1/API schemas; no v1 reinterpretation. |
| 2.10 — Workflow + Optional Demonstrators | Generic CI docs; deepen ecommerce; only if capacity, payments pack and JSONL/multi-JSON/bundle exports. | Provider semantics, broad pack catalog, CSV. | 2.7–2.9; documented end-to-end suite acceptance. | Additive docs/submodules; explicit bundle versions. |
| 2.11 — Performance + Scale Hardening | Benchmarks, aggregate bounds, streaming/memory verification, safe optimizations. | Throughput that weakens ordering/bounds. | All retained product features; targets and deterministic limit failures. | Tightening only within predeclared safety bounds; document limits. |
| 2.12 — Public Contract + Docs Freeze | Freeze exports/errors/DSL/schemas/CLI/docs/security/replay migration notes. | New features. | 2.11; complete contracts and backward tests. | Final additive API/DSL decisions; explicit replay posture. |
| 2.13 — Packaging + Fresh-Install RC | Version/package/console entry, build wheel/sdist, clean Python 3.11–3.14 installs. | Publication/tag/release. | 2.12; reproducible artifacts and full matrices. | Set RC/final 2.0 strategy; verify v1 remains installable separately. |
| 2.14 — Independent RC Acceptance | Independent source/artifact/hash/security/replay/CLI acceptance. | Repairs hidden in acceptance, publication. | 2.13; all independent gates green. | None except blocker reporting. |
| 2.15 — Explicit Publication | Authorized tag, PyPI upload, GitHub release, post-publish verification. | Force push, tag rewrite, further implementation. | 2.14 plus explicit authorization; immutable public hashes. | Publish 2.0.0 only when all contracts pass. |

## Velocity-Based Estimate

Repository evidence: v1 comprises 17 focused commits over roughly 72 hours, about 3,552 source lines, 280 collected tests plus 136 subtests, and successive implementation/freeze/repair loops. That cadence demonstrates very fast bounded vertical slices, but Phase 2 has deeper shared-schema, composition security, cross-version read, concurrency/order, CLI packaging, and release-review coupling than the mostly sequential Phase 0/1 slices. Estimates assume the same focused single-maintainer velocity but include explicit repair and independent acceptance loops.

- **Aggressive:** 5–7 weeks for must-haves, generic CI docs, bounds, and release gates; optional exports/reference additions deferred.
- **Likely:** 8–12 weeks for all must-haves, should-haves, one deepened reference pack, and robust fresh-install/independent RC loops.
- **Contingency:** 14–18 weeks if composition portability/security, manifest schema, parallel batch determinism, or replay/read compatibility requires redesign.
- **Highest risk:** deterministic multi-file composition, because identity, canonical hash, filesystem security, namespace resolution, manifests, replay, and every downstream suite feature converge there.
- **Critical path:** suite schemas → composition → matrix → batch/bundles → CLI/replay → scale/contracts → RC/acceptance/publication.
- **Easiest deferrals:** payments reference pack, export adapters, then oracle expansion depth; retain generic CI documentation and hard safety bounds.

From the 2026-09-03 freeze, the likely range is roughly late October through late November 2026; therefore late September 2026 is not supported by the measured likely range and is not a target.

## V1 Contract Validation

Pre-mutation validation ran from repository root `/Users/smshahinulislam/Developer/scenario-engine` on branch `main`. HEAD/main/origin-main were `ee29f52f714e84f17e1048ce24192fcf1c69345a`, tree `2a61915d578dcb1c4ec94049350a24d2cabdf721`, divergence `0/0`, with zero staged, unstaged, or untracked paths. The sole remote was `origin`, resolving to public `imshahinul/deterministic-scenario-engine`; tag `1.0.0` peeled to the baseline and its tree.

Validation used CPython 3.14.6 in isolated environment `/tmp/dse-phase2-0a-venv`, pytest 9.1.1, PyYAML 6.0.3, SQLAlchemy 2.0.52, Hypothesis 6.167.1, and Schemathesis 4.25.2, with repository `src` on `PYTHONPATH`. Canonical validation is `python -m pytest -q`; collection is `python -m pytest --collect-only -q`. It collected 280 tests and the full run passed: `280 passed, 136 subtests passed` in 41.94 seconds. Focused golden enforcement passed 4 tests and 3 subtests.

The actively enforced SHA-256 result goldens are:

| Case | SHA-256 | Enforcement |
|---|---|---|
| Cart | `cffc2e482f304ab18d39f96166e3e1be78b117a86bf0ce8ad0e22973677001b5` | Phase 1.0c result/canonical contract and Phase 1.0e RC test |
| Structured control flow | `86511d8c750272283eb1039a6e1039c8faa11cb5945c76aec41d9f5a71588e2b` | Phase 1.0c literal flow hash and Phase 1.0e RC test |
| Oracle/provenance | `5760aee1293d2d264d841621de08734358b3eb4ca54ef3e08e5a0b97f8f16cdd` | Phase 1.0c advanced result and Phase 1.0e RC test |

The Phase 1.0b tests enforce exact top-level exports, errors, lazy optional imports, and the primary journey. Phase 1.0c enforces YAML/DSL 1, Decimal semantics, result/manifest schema, canonical bytes, and exact replay compatibility. Phase 1.0d enforces documentation, examples, links, goldens, and the normative compatibility contract. Phase 1.0e enforces package/distribution/version/license/dependencies/pytest entry point. Public GitHub identity and PyPI 1.0.0 identity were independently confirmed; PyPI artifact hashes equal the immutable values above.

## Frozen Decision Register

| Decision | Frozen Value | Rationale |
|---|---|---|
| CLI | MUST_HAVE; `scenario` with validate/run/replay/hash/inspect/explain/diff/matrix/batch; library orchestration | Coherent end-to-end product without a second engine. |
| Composition | MUST_HAVE; one local namespaced `composition.modules` mechanism, depth-one, alias/content identity | Minimizes highest-risk semantics and makes suites reproducible. |
| Matrix | MUST_HAVE; ordered Cartesian expansion, pure filters, original index addressing, bounded stable case ID | Cases remain independently reproducible and order-safe. |
| Batch | MUST_HAVE; immutable explicit plans, independent contexts, plan-ordered results, bounded streaming | Worker/order independence is mandatory. |
| InspectExplain | MUST_HAVE; immutable structured library evidence, downstream renderers, no hidden trace | Existing deterministic records are sufficient authority. |
| StructuredDiff | MUST_HAVE; typed JSON-Pointer records, first/complete bounded modes | Semantic comparison, not raw text, supports CI and replay diagnosis. |
| OracleExpansion | SHOULD_HAVE; additive oracle assertions for result records | Existing oracle is the correct layer; no redundant abstraction. |
| DomainPacks | MUST_HAVE; explicit versioned declarative bundles distinct from generator plugins | Activates reusable domain semantics without discovery. |
| ReferencePacks | OPTIONAL; deepen ecommerce, at most one payments lifecycle addition | Demonstration value, not breadth. |
| ExportAdapters | OPTIONAL; JSONL/multi-JSON/fixture/bundle; CSV deferred | Downstream portability without alternate state/execution. |
| CIDeveloperWorkflow | SHOULD_HAVE; generic CLI/library docs and artifacts | Makes product operable without provider semantics. |
| PerformanceScale | SHOULD_HAVE; frozen hard bounds and baseline targets before optimization | Bounded deterministic behavior is release integrity. |
| ReleaseVersionStrategy | Eventual package 2.0.0; no version change in 2.0A | New suite/manifest/CLI contract is materially major. |
| DSLVersionStrategy | Retain DSL version 1 with additive, non-reinterpreting syntax | Package and DSL compatibility are separate. |
| V1ManifestReading | Supported through non-executing versioned read model | Enables diagnostics without replay promise. |
| V1Inspection | Supported | Structured read is safe and useful. |
| V1Diff | Supported, including v1-to-future normalized artifacts | Diff compatibility does not imply execution compatibility. |
| V1ExecutionReplay | Explicitly rejected by default under policy A; frozen v1 installation remains executor | No complete v1 executor is promised inside Phase 2. |
| NetworkImports | Forbidden | Network state cannot be deterministic or safely bounded here. |
| AutomaticDiscovery | Forbidden for plugins and domain packs; no entry-point/global/dynamic loading | Explicit registration preserves trust and reproducibility. |
