# Phase 3 Product Scope and Architecture Freeze

## 1. Status and frozen baseline

Status: **proposed architectural freeze for checkpoint 3.0A**. This document is a
decision artifact only. It authorizes no Phase 3 implementation, API, CLI,
schema, dependency, version, tag, release, or publication change. Every roadmap
checkpoint requires separate authorization and must use one bounded
prompt/validation/evidence/freeze cycle.

The immutable entry is distribution `deterministic-scenario-engine==2.0.0`,
commit `247edeacc2aae56f44be8a043f2d78bc325f7b02`, tree
`ddbd1cd8a34179e677b7e1ef0f54e2dcc1789144`, and annotated tag `2.0.0` peeled to
that commit. Historical tag `1.0.0` remains peeled to
`ee29f52f714e84f17e1048ce24192fcf1c69345a`. The frozen Phase 2 architecture is
`docs/phase2-architecture.md`, SHA-256
`ca54465a88ee92cb6f14bbe4ecf03e709e31f33e724fcf07d7af9d6b0e42664e`, and is
immutable historical architecture.

The four independent version roles remain:

| Role | Frozen entry value |
|---|---|
| Distribution | `2.0.0` |
| `ENGINE_VERSION` | `1.0.0` |
| `manifest.engine_version` | `1.0.0` |
| DSL | integer `1` |

The accepted historical regression reference is 466 tests and 144 subtests.

Repository inspection found a documentation defect in the 2.0 baseline:
`README.md` and `docs/phase2-public-contract.md` still describe 2.0.0 as
unpublished even though PyPI and the GitHub Release exist. This checkpoint does
not repair it; a future documentation checkpoint must correct current release
status without rewriting frozen Phase 2 architecture.

## 2. Phase 2 frozen product inventory

The inventory distinguishes solved behavior from partial work, deliberate
deferral, protected non-goals, and genuinely missing product capability.

| Product area | Status at 2.0 | Evidence and boundary |
|---|---|---|
| Core deterministic engine | **SOLVED** | Atomic in-memory state transitions, addressed RNG/IDs, logical clock, history, artifacts, faults, provenance, invariants, constraints, and oracle evaluation. |
| DSL | **SOLVED** | Safe strict DSL 1 parser/compiler/runtime; additive Phase 2 composition, matrix, and Oracle Assertion declarations do not reinterpret old documents. |
| Reproducibility manifests/results | **SOLVED** | Canonical `ScenarioResult`, exact core manifest compatibility tuple, and versioned suite envelopes. |
| Suite/read contracts | **SOLVED** | Bounded immutable run/suite/matrix/batch/read models and canonical serialization; v1 non-executing readers. |
| Deterministic composition | **SOLVED** | Explicit local root, depth-one namespaced modules, canonical hashes, traversal/symlink defenses, no remote imports. |
| Parameters/matrix | **SOLVED** | Ordered bounded Cartesian expansion, pure filters, stable case IDs, original indexes, independent case execution. |
| Deterministic batch | **SOLVED** | Explicit immutable plans, worker-independent ordered outcomes, bounded concurrency/retention, serial fail-fast. |
| Inspect/explain | **SOLVED** | Versioned immutable redacted evidence for core and suite artifacts; unavailable evidence is not invented. |
| Structured semantic diff | **SOLVED** | Typed RFC 6901 records, stable ordering, first/complete bounded modes, cross-read-model comparison. |
| CLI | **SOLVED** | Nine library-backed local commands with stable JSON/output/exit contracts. It is not remote orchestration. |
| Domain Packs | **SOLVED FOUNDATION** | Explicit immutable registry, exact versions, canonical declarative assets, no discovery/dependencies/global registry. A broad content ecosystem is not supplied. |
| Oracle Assertions | **SOLVED FOUNDATION** | Pure bounded post-result assertions over recorded normalized evidence. It is intentionally not an arbitrary query language. |
| Plugin surface | **SOLVED** | Explicit trusted unsandboxed registry with exact algorithm versions; no discovery. |
| pytest integration | **SOLVED** | Thin optional fixture/marker integration over public execution APIs. |
| SQLAlchemy integration | **SOLVED, DELIBERATELY NARROW** | Transactional post-result row materialization; no DB/ORM-owned scenario state, migration, or reflection discovery. |
| Hypothesis integration | **SOLVED, DELIBERATELY NARROW** | Explicit independently replayable case generation; no hidden strategy semantics. |
| Schemathesis integration | **SOLVED, DELIBERATELY NARROW** | Local case generation/binding only; automatic HTTP execution remains a non-goal. |
| Developer/CI workflow | **SOLVED FOUNDATION** | Generic bounded GitHub workflow exercises public CLI and retains deterministic evidence; no provider semantics in core. |
| Performance/scale bounds | **SOLVED** | Contract-tested hard limits for composition, matrix, batch, inspection, diff, packs, assertions, CLI, and aggregate work. |
| Public contract | **SOLVED/FROZEN** | Exact top-level and subpackage exports, errors, schemas, CLI, security, compatibility, and docs were frozen for 2.0. |
| Packaging/release model | **SOLVED** | One stable Python distribution, one core dependency, isolated extras, console/pytest entry points, wheel/sdist, tag, PyPI, and GitHub Release. |
| Reference Packs | **PARTIALLY SOLVED** | Ecommerce remains primarily a reference plugin factory; Phase 2 deferred a deep Domain Pack demonstrator and payments lifecycle pack. |
| Export/adaptor surface | **GENUINELY MISSING / DEFERRED** | Only single-result JSON-file and SQLAlchemy adapters exist. Multi-result JSON, JSONL, fixture directories, portable manifest/result bundles, and a formal adapter protocol were deferred. |
| Artifact migration tooling | **GENUINELY MISSING / DEFERRED** | Older artifacts can be read/inspected/diffed, but no validate/upgrade/copy migration product exists. |
| External orchestration | **PROTECTED NON-GOAL** | Batch is bounded in-process orchestration; DSE is not a workflow service, distributed scheduler, queue, or remote worker system. |

Phase 3 therefore must not rebuild suite generation, composition, matrix, batch,
inspection, diff, packs, assertions, or the nine-command CLI.

## 3. Product thesis and competing directions

> **Phase 3 evolves DSE from a deterministic scenario-suite generator into a portable deterministic evidence interchange product while preserving explicit execution, local trust boundaries, and the frozen 2.0 semantic engine.**

The primary users are test-platform engineers and application/test developers
who already generate deterministic suites and need to move their evidence
reliably between local runs, CI, storage, review, and downstream tools.

Credible alternatives were considered:

1. **Broader domain content.** Rich packs improve onboarding, but content breadth
   does not close the cross-tool lifecycle and risks turning Phase 3 into a pack
   catalog. Retain one deep reference demonstrator as supporting work.
2. **Remote/distributed orchestration.** It is a different operational product,
   introduces network/scheduler semantics, and conflicts with protected
   boundaries. Reject it for Phase 3.
3. **A richer assertion/query language.** Phase 2 already supplies the bounded
   assertion foundation. Arbitrary querying expands authority and security risk;
   only narrowly evidenced additive selectors should be optional later.
4. **Automatic integration/discovery.** Convenience does not justify ambient
   semantics or code-loading risk. Keep registration and I/O explicit.

Portable evidence is narrow and coherent: it builds downstream of completed
execution, manifests, inspection, and diff; it does not create another engine.
A candidate belongs in Phase 3 only if it improves bounded production,
validation, transport, consumption, or compatibility management of deterministic
evidence without acquiring hidden execution authority.

## 4. Target users, problems, and major user-value analysis

| Capability | Target user / concrete use case | 2.0 limitation | Proposed Phase 3 capability and why inside DSE | Determinism / compatibility / trust | Surface, complexity, dependencies |
|---|---|---|---|---|---|
| Canonical evidence bundle | CI/test-platform engineer archives a matrix or batch with manifests/results and later verifies it | No first-class portable multi-artifact container or relationship/hash index | A versioned immutable bundle index, canonical file layout, content hashes, and bounded validator. DSE owns canonical models and compatibility tuples, so external invention would fragment them. | Alias/ID sorted index, canonical bytes, explicit provenance; additive new schema; untrusted data only parsed, never executed | New `scenario_engine.export` or `artifacts` submodule and additive CLI commands; high complexity; requires current serializers/readers |
| Streaming export | Large-suite user feeds ordered results to artifact storage without retaining all output | Batch stream exists, but no supported JSONL/multi-result sink contract | Canonical JSONL and multi-result exporters consuming existing result envelopes. DSE must define typed encoding/order/hash semantics. | Plan/case order, one canonical object per record, byte/accounting bounds; no implicit destination | Additive Python adapter API and CLI flags/command; medium complexity; depends on bundle identity and batch/matrix streams |
| Explicit adapter protocol | Tool author maps evidence to an external sink or report | Existing adapters are unrelated concrete functions | A small push/pull-neutral protocol for normalized evidence records, capability declaration, deterministic receipt, and explicit caller construction. It belongs in DSE because accepted records and ordering are DSE contracts. | Adapter side effects are outside core; deterministic receipt records only declared outcomes; exact adapter name/version recorded when semantic | Additive submodule, no discovery; medium complexity; depends on export records |
| Artifact validation and migration planning | Maintainer receives v1/v2/Phase 3 evidence and needs actionable upgrade diagnostics | 2.0 reads some v1 artifacts but has no general validation report or migration plan | Non-executing validation plus explicit lossless migration where provable; dry-run plan otherwise. DSE owns schema provenance and can distinguish read from replay. | Canonical source hash, target schema, ordered transformations, loss report; parsing never loads code | Additive library/CLI; high complexity; depends on schema inventory and bundle validator |
| Deep reference evidence pack | New user needs one end-to-end realistic portable workflow | Ecommerce plugin exists, but no deep Domain Pack/bundle demonstration | Promote/deepen ecommerce as a declared Domain Pack demonstrating composition, matrix, batch, assertions, bundle, inspect, and diff. One coherent pack validates product cohesion. | Exact pack/plugin versions and asset hashes; trusted explicit registration | Existing/new reference module and docs/examples in a later checkpoint; medium complexity; depends on core interchange |
| Richer analysis summaries | CI reviewer needs deterministic aggregate pass/fail/change summaries | Inspection/diff are record-level and can be verbose | Optional pure bounded aggregate views over existing evidence, not a query language. Inside DSE only where semantic typing is required. | Stable grouping/order, explicit unavailable/truncated fields; additive schemas | Additive inspection API/CLI rendering; medium complexity; depends on bundles; optional |

## 5. Candidate inventory and exact classification

Every repository-supported candidate is classified exactly once.

| Candidate | Classification | Architectural reason and provenance |
|---|---|---|
| Versioned canonical evidence bundle (index + manifests + results) | **MUST_HAVE_PHASE3** | Phase 2 explicitly deferred bundle export; this is the minimum coherent interchange unit. |
| Bounded bundle validation with content/relationship hashes | **MUST_HAVE_PHASE3** | Portability without offline integrity and schema validation would not preserve reproducibility. |
| Canonical ordered JSONL and multi-result JSON export | **MUST_HAVE_PHASE3** | Explicit Phase 2 export candidates and necessary streaming interchange forms. |
| Explicit versioned evidence-adapter protocol, no discovery | **MUST_HAVE_PHASE3** | Productized interoperability needs one narrow extension boundary rather than bespoke sinks. |
| Non-executing artifact compatibility report and migration planner | **MUST_HAVE_PHASE3** | Converts existing reader/replay distinctions into safe operational guidance. |
| Lossless migrations between supported additive artifact revisions | **SHOULD_HAVE_PHASE3** | Valuable only where preservation can be proven; must never claim execution compatibility. |
| Fixture-directory exporter using stable IDs | **SHOULD_HAVE_PHASE3** | Explicitly deferred in Phase 2 and useful for test repositories; downstream only. |
| Deepened ecommerce Domain/Reference Pack workflow | **SHOULD_HAVE_PHASE3** | Demonstrates the thesis end to end without broad catalog accumulation. |
| Deterministic aggregate analysis summaries | **OPTIONAL_PHASE3** | Helpful for CI consumption but existing inspect/diff already solve core diagnosis. |
| Payments/order-lifecycle Reference Pack | **OPTIONAL_PHASE3** | Include only if it proves materially different Decimal, idempotency, fault, and transition behavior. |
| Additional Oracle Assertion selectors/operators | **OPTIONAL_PHASE3** | Allowed only when interchange demonstrations expose a concrete gap; no new query language. |
| Additional composition/matrix/batch convenience APIs | **OPTIONAL_PHASE3** | Only thin additive ergonomics supporting evidence export; core semantics are complete. |
| CSV export | **DEFER_POST_PHASE3** | Nested typed values require a separately designed lossy flattening contract. |
| Broad Reference Pack catalog (SaaS/users/inventory/API) | **DEFER_POST_PHASE3** | Dilutes the narrow interchange thesis and increases maintenance breadth. |
| Database/object-store/cloud-provider adapters shipped in core | **DEFER_POST_PHASE3** | Protocol first; provider behavior, credentials, retries, and dependencies remain external. |
| Distributed scheduler, remote workers, queue/service orchestration | **REJECT / REMAIN_NON_GOAL** | Network and scheduling become product semantics; DSE remains bounded library/CLI execution. |
| Automatic plugin/Domain Pack/adapter discovery | **REJECT / REMAIN_NON_GOAL** | Ambient code loading violates trust and reproducibility boundaries. |
| Remote composition or automatic network artifact retrieval | **REJECT / REMAIN_NON_GOAL** | Hidden/external state would weaken deterministic and security guarantees. |
| Arbitrary assertion/query/Python language | **REJECT / REMAIN_NON_GOAL** | Expands execution authority and duplicates external analysis tools. |
| v1 execution replay inside current engine | **REOPEN_REQUIRES_EXPLICIT_USER_DECISION** | Phase 2 explicitly rejected this absent a separately reviewed complete compatibility proof. |
| Nested composition or recursive subflows | **REOPEN_REQUIRES_EXPLICIT_USER_DECISION** | Existing depth/recursion boundary is deliberate and security-sensitive. |
| Automatic Schemathesis HTTP execution | **REOPEN_REQUIRES_EXPLICIT_USER_DECISION** | Current integration deliberately binds local cases only. |

## 6. Phase 3 scope, deferred scope, and explicit non-goals

### In scope

Phase 3 defines a versioned evidence interchange layer downstream of execution:
bundle models and canonical layout; ordered streaming exporters; bounded offline
validation; explicit adapter contracts; compatibility/migration reports;
provably lossless transformations; one deep reference workflow; and the public,
performance, security, packaging, and release work necessary to support them.

### Deferred

CSV/flattening, broad pack catalogs, provider-specific or credentialed sinks,
cloud SDK dependencies, remote storage clients, dashboards, distributed runs,
and speculative assertion/composition/batch breadth are deferred.

### Protected non-goals

The following remain prohibited: arbitrary Python execution from YAML; hidden
randomness; wall-clock semantic dependence; hidden network execution; automatic
network composition imports; automatic plugin, Domain Pack, Reference Pack, or
adapter discovery; YAML dynamic imports; implicit environment-driven semantics;
global mutable registries; recursive/unbounded subflows; unbounded loops;
DB-backed or ORM-owned `ScenarioState`; raw SQL DSL; automatic Schemathesis HTTP
execution; and indefinite incompatible cross-major replay. DSE is not a general
sandbox, workflow engine, distributed scheduler, database migration framework,
or artifact hosting service.

## 7. Architectural components and data/model boundaries

1. **Evidence record layer.** A tagged immutable envelope references existing
   run/suite/matrix/batch manifests and canonical result/evaluation/inspection/
   diff payloads. Existing 2.0 values are embedded or referenced, never mutated.
2. **Bundle index.** A new independently versioned root records bundle identity,
   ordered logical entries, media/schema kinds, byte sizes, SHA-256 hashes,
   relationships, provenance, and optional adapter receipts. Physical absolute
   paths, mtimes, owners, permissions, host names, and directory enumeration are
   not semantic.
3. **Canonical layout/export.** A deterministic relative POSIX layout uses
   normalized stable IDs rather than user text. JSON and JSONL share existing
   typed semantic encodings. Export is downstream and executes nothing.
4. **Bounded reader/validator.** Safe parsing validates syntax, schemas, hashes,
   identity links, counts, sizes, and compatibility without importing plugins,
   packs, adapters, or executing a scenario.
5. **Compatibility/migration planner.** Produces immutable ordered diagnostics
   and transformations. It separately reports readability, inspection, diff,
   execution, replay, and migration; it cannot infer one from another.
6. **Adapter boundary.** A caller explicitly constructs an immutable adapter
   with exact identity/version and declared capabilities, then supplies records.
   Core does not discover, configure, retry, credential, or sandbox it.
7. **Reference workflow.** Trusted explicitly imported reference content proves
   generation → assertion → export → validate → inspect/diff. It is not loaded
   by YAML or bundle readers.

Scenario execution remains owned by the frozen engine and DSL layers. Bundle
reading never returns executable Python objects merely because metadata names a
plugin or pack. Migration operates on validated data models; replay remains a
separate explicit operation gated by the complete compatibility tuple.

## 8. Extension and public-surface strategy

| Surface | Classification | Phase 3 strategy |
|---|---|---|
| Core engine, state, RNG, IDs, clock | **internal/frozen** | No semantic change planned. |
| Existing package-root API | **compatibility-sensitive public** | Preserve exact 2.0 names/order; new features begin in explicit subpackages. |
| Evidence/bundle/export APIs | **additive public** | New immutable models, serializers, validators, exporters, adapter protocol, errors, and constants under one cohesive subpackage. |
| CLI | **compatibility-sensitive public + additive public** | Preserve nine commands/options/exits. Add an `artifact` command group or narrowly named `export`, `verify`, and `migrate` commands only after CLI contract review. JSON schemas and exits are explicit. |
| Existing artifacts/manifests/schemas | **compatibility-sensitive public** | Do not rewrite. Consume through adapters/read models. |
| Bundle/migration/receipt schemas | **additive public** | New independently versioned contracts. |
| Plugin and Domain Pack contracts | **compatibility-sensitive public** | No discovery or changed execution authority; exact versions/hashes remain required. |
| Evidence adapter contract | **additive public** | Explicit caller registration/construction only; adapter code trusted and unsandboxed. |
| Oracle Assertions | **compatibility-sensitive public** | Existing schema unchanged unless a separately justified additive revision is approved. |
| Documentation/examples | **additive public** | Correct stale release status and document trust, formats, migrations, and end-to-end reference workflow at contract freeze. |
| Dependencies/package extras | **deferred/compatibility-sensitive** | Core interchange uses the standard library and existing normalization where possible. Provider dependencies are not added to core. |

The CLI remains a renderer/orchestrator over public library operations, not an
independent implementation. Machine output is canonical UTF-8 JSON plus LF,
with stdout/stderr separation and no progress/timing/host-path semantics.

## 9. Artifact, schema, and version strategy

### Distribution

The evidence-supported eventual target is **2.1.0**, not 3.0.0. The Phase 3
product name is a planning phase, not a SemVer instruction. Its primary surfaces
can be additive while preserving all 2.0 API, CLI, DSL, engine, and artifact
behavior. A 3.0.0 distribution is required only if an implementation checkpoint
proves a necessary break to a supported 2.0 contract; that would require an
explicit architecture reopening and user authorization. No version changes in
3.0A.

### Engine and DSL

Keep `ENGINE_VERSION == "1.0.0"`: export, validation, and migration are
downstream and do not alter deterministic execution semantics or core replay
bytes. Keep DSL integer `1`: no syntax is required for evidence interchange.
Any change to valid DSL 1 meaning requires a new integer DSL version and an
explicit breaking-contract decision; none is proposed.

### Current versioned contracts

| Contract | 2.0 version | Phase 3 decision |
|---|---|---|
| Core result / `ReproducibilityManifest` | engine/DSL tuple (`1.0.0`, `1`) | **No change**. |
| Run envelope | `suite.run/1` | **No change**; bundle references/embeds it. |
| Suite manifest | `suite.manifest/1` | **No change**. |
| Matrix manifest | `suite.matrix/1`, `matrix.case/1` | **No change**. |
| Batch manifest | `suite.batch/1`, `batch.plan/1` | **No change**. |
| Historical read model | `suite.artifact-read/1` | **Additive compatible extension only if new recognized origins are needed**; prefer a new bundle reader model. |
| Composition | `composition.modules/1` | **No change**. |
| Matrix plan identity | `matrix.plan/1` | **No change**. |
| Batch plan identity | `batch.plan/1` | **No change**. |
| Inspection / explanation | `inspection.document/1`, `inspection.explanation/1` | **No change** initially; a new aggregate view gets its own schema. |
| Semantic diff | `semantic.diff/1` | **No change** initially. |
| Domain Pack | `domain-pack/1` | **No change**. |
| Oracle assertion/evaluation | `oracle.assertion/1`, `oracle.evaluation/1` | **No change** unless optional operators force a reviewed additive revision. |
| Evidence bundle | none | **New schema revision** `evidence.bundle/1` proposed. |
| Evidence record/index entry | none | **New schema revision** proposed under the bundle family. |
| Adapter receipt/capability | none | **New schema revision** proposed; exact adapter identity/version. |
| Compatibility/migration report | none | **New schema revision** proposed; non-executing and loss-explicit. |

Schema versions increase only when accepted fields/defaults/semantics cannot be
represented compatibly. A migration is never in-place: it creates a new
canonical artifact linked to the source hash and transformation version.

## 10. Compatibility matrix

Terms describe distinct capabilities and must not be collapsed.

| Artifact → Phase 3 consumer | Phase 3 support |
|---|---|
| v1 result/manifest | **READABLE, INSPECTABLE, DIFFABLE, MIGRATABLE** only where a lossless wrapper is defined; **UNSUPPORTED** for current-engine execution/replay. |
| v1 DSL scenario | **READABLE, EXECUTABLE, REPLAYABLE** only under the current engine's ordinary DSL/core compatibility checks for artifacts it itself produced; a recorded incompatible v1 artifact remains **UNSUPPORTED** for replay. |
| 2.0 core result/manifest | **READABLE, INSPECTABLE, DIFFABLE**; **REPLAYABLE/EXECUTABLE** only with exact current compatibility tuple and explicit scenario/inputs/registries. |
| 2.0 suite/composition manifest | **READABLE, INSPECTABLE, DIFFABLE**; execution/replay requires explicit local source bytes/root and matching hashes; migration to bundle index is **MIGRATABLE** without changing child artifacts. |
| 2.0 matrix artifact | **READABLE, INSPECTABLE, DIFFABLE**; case execution/replay only with exact suite/case context; wrapper migration is **MIGRATABLE**. |
| 2.0 batch artifact | **READABLE, INSPECTABLE, DIFFABLE**; successful children are individually replayable when compatible; batch record itself is not an execution-state store; wrapper migration is **MIGRATABLE**. |
| 2.0 Domain Pack record | **READABLE, INSPECTABLE, DIFFABLE**; **EXECUTABLE/REPLAYABLE** only with explicit trusted exact registry/version/hash. |
| 2.0 Oracle Assertion/evaluation | **READABLE, INSPECTABLE, DIFFABLE**; evaluation is executable only as a pure explicit operation over supported recorded evidence, never by bundle read. |
| Phase 3 bundle/report/receipt → Phase 3 reader | **READABLE, INSPECTABLE, DIFFABLE**; bundle validation is non-executing; child execution/replay follows each child's compatibility. |
| Phase 3 bundle/report/receipt → 2.0 reader | **UNSUPPORTED** as a new container/schema. Embedded unchanged 2.0 child bytes remain separately readable by 2.0 when extracted by a trusted compatible tool. |
| Future revised 2.0 schema → Phase 3 reader | **UNSUPPORTED** unless explicitly enumerated; unknown versions fail closed. |

**Policy for 1.0 artifacts:** preserve bounded non-executing read, inspection,
and diff. Offer migration only when it is a lossless envelope/copy operation.
Do not promise execution replay; use the frozen 1.0 distribution for its exact
contract unless a separately authorized compatibility proof reopens the rule.

**Policy for 2.0 artifacts:** preserve supported 2.0 bytes and semantics. Phase
3 may package them unchanged and report compatibility. Exact execution/replay
requires the complete recorded tuple and explicit external inputs. Readability
never implies executability or replayability.

## 11. Replay and migration policy

Replay always validates source identity, canonical hashes, `ENGINE_VERSION`, DSL,
RNG, ID, generators/plugins, Domain Packs, explicit inputs/resources, locale,
logical clock, seed, run/case coordinates, and applicable suite contracts before
execution. A bundle is not an executor or state store. Opening, validating,
inspecting, diffing, exporting, or migrating a bundle never triggers replay.

Migration is explicit, offline, bounded, deterministic, and non-destructive.
Every report states source/target schema, source hash, transformation identity,
loss status, unsupported fields, child replay posture, and target hash. Only
lossless transformations may be labeled `MIGRATABLE`; lossy conversion requires
a different export operation and cannot replace a source. There is no automatic
migration on read and no indefinite cross-major promise.

## 12. Security and trust boundaries

- **YAML/scenarios:** untrusted declarative input; safe loader, duplicate/alias/
  merge/tag rejection, strict schema, bounded bytes/depth/counts. No Python,
  environment, network, or dynamic imports.
- **Plugins, Domain Packs, Reference Packs:** explicit trusted unsandboxed Python
  inputs. Exact identity/version/hash is recorded. Reference content gets no
  discovery privilege.
- **Bundles/imported/exported artifacts:** untrusted data. Validate paths,
  normalized IDs, media/schema types, duplicate entries, hashes, links, sizes,
  depth, and counts before materialization. Reading never imports or executes
  named code.
- **Adapters/integrations:** explicitly constructed trusted unsandboxed code and
  an external-side-effect boundary. Credentials/configuration are caller-owned,
  never serialized by default, and never sourced implicitly from environment by
  core APIs. Adapter failure cannot mutate accepted core results.
- **Filesystem:** explicit caller roots/destinations only. Relative POSIX bundle
  paths reject absolute/drive/UNC paths, `.`, `..`, empty segments, backslashes,
  NUL, URI schemes, case-fold collisions, symlinks, special files, and escapes.
  Writes reject overwrite by default and use atomic replacement when explicit.
- **Network:** core performs none. A third-party adapter may perform explicit
  caller-authorized I/O outside deterministic execution; network responses are
  never silently folded into scenario semantics or canonical result identity.
- **User-supplied content:** data is parsed/validated, not evaluated as Python,
  SQL, templates, shell, or arbitrary selectors. Diagnostic values/paths/secrets
  are redacted and bounded by default.

## 13. Deterministic guarantees

Every proposed capability must provide:

1. deterministic record and entry ordering from explicit semantic coordinates,
   never directory enumeration, set/map iteration, worker completion, or host;
2. deterministic stable IDs as SHA-256 of versioned canonical envelopes, with
   collision treated as failure rather than coalescing;
3. canonical UTF-8 JSON typed normalization, sorted object keys, declared
   sequence order, and exact newline rules for JSONL/CLI;
4. controlled root seeds and unchanged addressed RNG/ID algorithms for any child
   execution; exporters and readers consume no randomness;
5. provenance linking source hash, child hash, transformation/export contract,
   explicit adapter identity/version, and output hash;
6. existing reproducibility manifests preserved byte-for-byte when embedded;
7. explicit external-input boundaries: caller paths, adapter configuration,
   credentials, network outcomes, and storage receipts are never hidden semantic
   inputs; and
8. deterministic error precedence and bounded safe diagnostics.

Adapter side effects themselves may be nondeterministic. DSE guarantees the
ordered canonical records presented to the adapter and the normalized declared
receipt, not external service timing or availability.

## 14. Resource and scalability bounds

Existing 2.0 bounds remain authoritative. Phase 3 implementation must finalize
constants no looser than these architectural ceilings:

| Area | Frozen Phase 3 ceiling |
|---|---:|
| Bundle entries | 100,000 |
| Bundle index canonical bytes | 16 MiB |
| Individual artifact bytes | 256 MiB, additionally constrained by its native schema |
| Aggregate bundle bytes per validation/export call | explicit caller limit, default 256 MiB, hard 4 GiB |
| Bundle path depth / semantic nesting | 64 / 64 |
| JSONL records | 100,000 per stream |
| Adapter in-flight records | explicit, default 64, hard 1,024 |
| Adapter receipt bytes | 1 MiB per receipt; 16 MiB aggregate |
| Migration transformations | 1,000 records in a plan; no recursive migration chains |
| Inspection/diff | existing 100,000-record/depth/item/byte ceilings remain |
| Composition | existing 64 modules, depth 1, and byte bounds remain |
| Matrix/batch/assertions | existing 10,000 retained cases, 10,000 requests, and 1,000 assertions remain |
| Loops/subflows | existing bounded repeat; recursion remains forbidden |
| Execution | existing step/history/artifact/provenance and aggregate-work limits remain; exports cannot raise them |

Bounds are checked before allocation/work where practical. Streaming may reduce
memory but cannot weaken total byte/record limits, order, hash verification, or
error precedence. Archive compression, if ever proposed, requires separate
compressed and expanded size/ratio limits; it is not initially required.

## 15. Packaging implications

The preferred implementation adds no core runtime dependency. Canonical files,
hashing, atomic writes, and protocols can use the standard library and existing
normalization. Provider adapters remain separately packaged third-party code;
no cloud/database SDK enters core or automatic entry points. New package data is
limited to deliberate reference assets and documentation after manifest/wheel
tests prove inclusion. Distribution version changes only at the packaging/RC
checkpoint. No tag, GitHub Release, or PyPI publication occurs before the final
explicit publication checkpoint.

## 16. Testing strategy

Each slice preserves the full historical suite and adds focused tests for:

- exact canonical bytes/hashes, round trips, unknown/duplicate fields, Unicode,
  typed values, stable ordering, deterministic errors, and schema bounds;
- malicious paths, symlink/special-file escapes, zip-bomb-style expansion if
  archives are later authorized, oversized/deep input, hash/link mismatch, and
  proof that reading invokes no plugin/pack/adapter/network/execution;
- stream versus retained byte identity, partial-write cleanup, overwrite policy,
  worker/order independence, and bounded memory;
- v1/v2/Phase 3 compatibility matrix cases, especially read ≠ execute ≠ replay;
- lossless migration source/target hashes, dry runs, unsupported/loss reports,
  idempotence, and no in-place mutation;
- adapter contract conformance using local deterministic fakes, without network;
- the deep reference workflow through library and CLI; and
- source/wheel/sdist/fresh-install matrices on supported Python versions.

Performance tests measure worst-case valid bundle index, streaming 100,000 small
records, maximum native artifacts, validation/hash throughput, and migration
memory. Optimization cannot alter bytes, ordering, errors, or bounds. Security
review and an independent RC acceptance remain separate gates.

## 17. Release strategy

Phase 3 ships only after implementation, hardening, and public-contract freeze.
The expected additive release is 2.1.0. Release candidates are built from a
clean frozen commit, installed in clean supported Python environments, and
tested from wheel and sdist. Independent acceptance verifies hashes, contents,
exports, schemas, CLI, migration claims, trust boundaries, older artifacts, and
absence of publication. Tagging, PyPI upload, and GitHub Release are one final
separately authorized checkpoint; publication is never implied by RC acceptance.

## 18. Implementation milestone roadmap

No checkpoint below is authorized by this architecture document.

| Checkpoint | Objective | Authorized source surface | Invariants / expected tests | Blockers and dependencies | Public/version effect |
|---|---|---|---|---|---|
| **3.0A — Entry / Scope / Architecture Freeze** | This docs-only evidence-derived freeze | `docs/phase3-architecture.md` only | Baseline, docs consistency, forbidden-diff checks, full regression | Canonical 2.0 entry | None |
| **3.1 — Evidence Models + Canonical Bundle Contract** | Immutable index/entry/relationship models and canonical serialization | New evidence subpackage + focused tests/docs | Existing artifacts unchanged; bytes/hash/schema/bounds tests | 3.0A | Additive public schemas/APIs; no engine/DSL bump |
| **3.2 — Safe Bundle Reader + Validator** | Bounded offline directory reader, link/hash/schema verification | Evidence reader/validator + tests | Traversal/symlink/special-file/size/depth/duplicate/no-execution tests | 3.1 | Additive public API/errors |
| **3.3 — Ordered JSON/JSONL + Bundle Export** | Atomic retained/streaming exporters over run/matrix/batch records | Export submodule + tests | Stream/retained identity, order, typed values, cleanup/overwrite/memory | 3.1–3.2 | Additive public API/artifact formats |
| **3.4 — Explicit Evidence Adapter Contract** | Caller-created versioned protocol and normalized receipts | Adapter protocol + deterministic fake tests | No discovery/global registry; ordering, backpressure, failure isolation | 3.3 | Additive public contract; no provider dependency |
| **3.5 — Compatibility Reports + Migration Planner** | Distinct capability reporting and deterministic dry-run plans | Compatibility/migration submodule + tests | Full matrix, no code loading/replay, source hashes, loss declaration | 3.2 | Additive public reports/schemas |
| **3.6 — Lossless Migrations + Fixture Export** | Approved copy/envelope transformations and stable fixture layout | Migration/export implementation + tests | Non-destructive, idempotent, source/target hashes, unsupported fails closed | 3.3, 3.5 | New schema revisions only if proven necessary; no replay promise |
| **3.7 — CLI Interchange Surface** | Thin export/verify/migrate operations and stable machine output | CLI + tests/docs | Existing nine commands byte/exit compatible; streams, exits, redaction | 3.2–3.6 | Additive compatibility-sensitive CLI review |
| **3.8 — Deep Reference Evidence Workflow** | Ecommerce Domain/Reference Pack end-to-end demonstrator; optional payments only if justified | Reference pack, examples, docs, focused tests | Explicit registration, exact hashes, no network/discovery, reproducible bundle | 3.3, 3.7 | Additive content/API only; no core version bump |
| **3.9 — Optional Bounded Analysis** | Only evidence-backed aggregate summaries/assertion gaps | Inspection/assertion subpackages + tests | Pure bounded recorded-evidence analysis, no query language | 3.8 demonstrates need; otherwise skip | May add schema/API; requires focused compatibility review |
| **3.10 — Performance / Security Hardening** | Enforce ceilings, streaming memory, adversarial path/data review | Relevant implementation/tests/bench docs | Full regression, performance targets, fuzz/adversarial cases, no semantics drift | All retained features | Bound tightening only within frozen ceilings; no break |
| **3.11 — Public Contract + Docs Freeze** | Freeze exports/errors/schemas/CLI/security/migration/version; repair stale 2.0 release-status docs | Public docs and contract tests; only necessary source manifests | Exact API/CLI/schema/docs/link/backward tests | 3.10 | Final approval point for additive contract and 2.1.0 plan |
| **3.12 — Packaging / RC** | Set authorized version, build reproducible wheel/sdist, fresh installs | Packaging/version + RC tests | Python 3.11–3.14, dependency isolation, artifact contents/hashes | 3.11 | Expected distribution 2.1.0; no tag/publication |
| **3.13 — Independent RC Acceptance** | Immutable independent source/artifact/security/compatibility acceptance | No candidate edits; evidence only | All release, migration, older artifact, installation, and no-publication gates | 3.12 | None; failures require a separate repair checkpoint |
| **3.14 — Explicit Publication** | Tag/upload/GitHub Release/post-publication verification | Release state only as separately authorized | Exact commit/tag/artifact hashes, PyPI/GitHub identity | 3.13 + explicit user authorization | Publish approved version; no further implementation |

Every implementation checkpoint must enumerate exact authorized paths, reject
scope drift, run the full regression suite, create one candidate commit, perform
immutable post-commit acceptance, adopt only on complete success, and write one
evidence file.

## 19. Decisions requiring future explicit user authorization

The roadmap itself grants no implementation authorization. In addition to each
checkpoint, the following require an explicit user decision before reopening:

1. embedding or supporting v1 execution replay in the current engine;
2. nested composition, recursive subflows, or any increased recursion authority;
3. automatic Schemathesis HTTP execution or core-owned network operations;
4. automatic discovery/entry-point loading for plugins, packs, or adapters;
5. any distribution target other than additive 2.1.0 because implementation
   proved a supported 2.0 break unavoidable;
6. any `ENGINE_VERSION`, DSL integer, or existing schema-version bump;
7. archive/compression formats with expanded-content risks;
8. provider-specific adapters or new runtime dependencies; and
9. final tagging, GitHub Release creation, or PyPI publication.

Until separately authorized, `PHASE3_IMPLEMENTATION_STARTED=NO`.

## 20. Phase 3.1 implementation resolution

The separately authorized 3.1 checkpoint implements the declarative contract in
the additive `scenario_engine.evidence` subpackage. The first independent schema
family is `evidence.bundle/1`, `evidence.entry/1`,
`evidence.relationship/1`, and `evidence.provenance/1`. Bundle entries are sorted
by logical ID; relationships are sorted by `(source_id, kind, target_id)`.
Duplicate IDs, duplicate and case-fold-colliding paths, dangling/self/duplicate
relationships, malformed hashes, unsupported schema versions, and invalid
relative POSIX path values fail during model construction.

The canonical index is compact, key-sorted UTF-8 JSON with no trailing newline.
The bundle ID is lowercase SHA-256 over those exact canonical bytes; the derived
`bundle_id` property is omitted from its own hash envelope. Models use no clock,
randomness, environment, network, discovery, imports named by data, or I/O.

Phase 3.1 enforces intrinsic limits of 100,000 entries, 100,000 relationships,
16 MiB canonical index bytes, 256 MiB declared bytes per artifact, and 64 path
segments. It declares the 256 MiB default and 4 GiB hard aggregate-operation
ceilings for later operations. Aggregate physical bytes, native child-schema
limits, semantic payload depth, filesystem materialization, symlinks and special
files require actual input bytes or a filesystem root and are therefore deferred
to the bounded 3.2 reader/validator (and later exporters). This resolution adds
no reader, exporter, adapter, migration, CLI, execution, or retrieval behavior.

## 21. Phase 3.2 implementation resolution

The separately authorized 3.2 checkpoint adds one non-executing API,
`read_evidence_bundle(index_path, *, bundle_root, max_aggregate_bytes=...)`, under
`scenario_engine.evidence`. Both paths must be explicit absolute local paths and
the index must be beneath the root. Validation order is bounded index read,
strict UTF-8/duplicate-safe JSON and depth checking, exact 3.1 model
reconstruction and canonical-byte checking, semantic-order filesystem checks,
individual/declarative/aggregate physical-size checks, then streamed SHA-256.

Filesystem traversal uses directory-relative descriptors, no-follow opens, and
regular-file checks for the index, every intermediate component, and every
artifact. Files are reopened for hashing and identity/size/mtime are checked
across validation. These checks strongly constrain substitution but do not claim
a portable, completely race-free guarantee against a concurrently malicious
filesystem; callers must provide a locally trusted/stable root for that residual
TOCTOU boundary. Child bytes remain opaque. The reader performs no writes,
execution, replay, imports selected by data, discovery, network, subprocess,
environment-derived semantics, clock access, or randomness. Export and every
3.3+ capability remain deferred.

## 22. Phase 3.3 implementation resolution

The separately authorized 3.3 checkpoint adds three bounded APIs under
`scenario_engine.evidence`. `canonical_evidence_records_bytes` accepts a finite
explicit sequence of values under the existing DSE typed semantic normalization,
preserves semantic sequence order, sorts mapping keys, and returns one compact
UTF-8 JSON array without a newline. `write_evidence_jsonl` consumes records in
explicit caller order, streams one compact canonical value plus LF per record, writes zero bytes for an
empty stream, always includes the final LF for non-empty output, and returns the
SHA-256 of exact written bytes. Both enforce 100,000 records and an explicit byte
limit whose default is 256 MiB and hard ceiling is 4 GiB.

`export_evidence_bundle` accepts one existing `EvidenceBundle`, an explicit
absolute source root containing its declared paths, and an absent explicit
absolute destination. The canonical directory layout is `bundle.json` plus the
bundle's already validated relative POSIX entry paths. Child bytes are copied
unchanged in bounded chunks; size and SHA-256 are verified. An adjacent staging
directory is completed and validated through `read_evidence_bundle` before one
same-filesystem directory rename publishes it. Existing destinations and
symlinked/unsafe source or destination components fail closed; recoverable
failure removes staging and leaves the final destination absent. Temporary name
and chunk size are not identity inputs. As in 3.2, complete race freedom against
a concurrently hostile filesystem is not claimed; callers supply stable local
source and destination parents. Export performs no execution, discovery,
network, subprocess, environment-derived semantics, semantic clock access, or
semantic randomness. Adapters, receipts, migrations, fixture transformation,
CLI work, and every 3.4+ feature remain deferred.

## 23. Phase 3.4 implementation resolution

The separately authorized 3.4 checkpoint adds the structural `EvidenceAdapter`
protocol under `scenario_engine.evidence`. A caller supplies one trusted,
unsandboxed adapter instance directly. Its immutable
`evidence.adapter-capability/1` declaration records a portable adapter ID,
bounded adapter version, exact `evidence.adapter/1` contract, and exactly the
provider-neutral `publish-bundle` operation. There is no registry, entry-point
or module discovery, bundle/YAML selection, environment selection, credential
handling, provider configuration API, retry, or concrete provider.

`publish_evidence_bundles` passes existing validated `EvidenceBundle` objects to
that instance without parsing, rewriting, or changing bundle identity. Input
ordinals are assigned before bounded submission. A sliding window defaults to
64 and has a hard maximum of 1,024; it does not eagerly exhaust the input.
Optional standard-library worker concurrency cannot change returned input order.
The adapter returns only a bounded `EvidenceAdapterPublication` observation.
Core normalizes it to immutable `evidence.adapter-receipt/1` records retaining
adapter identity/version, source bundle ID, operation, ordinal, status, and an
optional external locator. Canonical capability and receipt bytes are compact,
key-sorted UTF-8 JSON without timestamps, randomness, process/host state, or
arbitrary provider mappings. Receipts are bounded by exact canonical bytes at
1 MiB individually and 16 MiB in aggregate.

Adapter exceptions are isolated as a stable `adapter.operation_failed` receipt;
raw exception text and objects are never persisted. Malformed declarations,
requests, or returns fail as typed contract errors, while failures of the core
or iterable boundary use a typed orchestration error. Successful prior external
side effects are not rolled back and no transaction is promised. Source bytes,
IDs, ordinals, normalization, ordering, and bound enforcement are deterministic;
adapter timing, availability, side effects, and returned provider locator are
explicitly not. The generic layer performs no external I/O except invoking the
explicit adapter method and never feeds a provider observation into scenario
execution. Compatibility/migration, fixture export, CLI additions, providers,
reference workflows, versions, and every 3.5+ capability remain deferred.

## 24. Phase 3.5 implementation resolution

The separately authorized 3.5 checkpoint adds pure metadata-driven compatibility
reporting and migration planning under `scenario_engine.evidence`. The immutable
`ArtifactDescriptor` contains only artifact kind, versioned schema, product
version, optional lowercase source SHA-256, and a bounded sorted tuple of explicit
requirement coordinates. It does not accept arbitrary metadata or paths and does
not parse payload bytes.

`evidence.compatibility-report/1` reports the current consumer contract and one
ordered determination for every positive capability: `READABLE`, `INSPECTABLE`,
`DIFFABLE`, `EXECUTABLE`, `REPLAYABLE`, and `MIGRATABLE`. `UNSUPPORTED` is the
aggregate capability only when no positive capability applies. Each determination
has a supported/unsupported disposition, a finite reason code, and sorted explicit
requirements. Missing and mismatched execution coordinates remain unsupported;
readability never implies execution, and container readability never implies
child execution.

`evidence.migration-plan/1` contains a source descriptor, target contract,
disposition, finite reason, ordered declared-lossless steps, and SHA-256 plan
identity. The only frozen routes are one-step wrappers of unchanged v1 result or
manifest bytes and unchanged v2 suite, composition, matrix, or batch bytes into
`evidence.bundle/1`. These plans require preserving source bytes and SHA-256 and
do not claim replay support. Every other pair has no lossless path. Plans are
acyclic, contiguous, non-recursive, and bounded to 1,000 steps. If finite policy
ever has several routes, selection is fewest steps then lexical transformation-ID
sequence.

Report and plan bytes are compact sorted-key UTF-8 JSON without a newline; hashes
are SHA-256 of those exact bytes. The finite internal matrix fails closed for
unknown schemas and product versions and cannot be expanded by discovery. Neither
API reads files or environment, imports data-selected code, traverses bundles,
loads plugins or Domain Packs, invokes adapters/assertions/scenarios, executes a
migration, performs network/subprocess I/O, observes time, or uses randomness.
Migration execution and fixture export remain deferred to 3.6.

## 25. Phase 3.6 implementation resolution

The separately authorized 3.6 checkpoint executes exactly the six frozen 3.5
one-step wrapper routes through a private static transformation map. Execution
requires the accepted plan and matching descriptor, verifies declared source
SHA-256 while copying in bounded chunks, preserves source bytes unchanged as the
single bundle child, records source-hash provenance, and publishes through the
3.3 atomic bundle exporter. Unknown, lossy, malformed, unsupported, cyclic, or
noncontiguous plans fail closed; execution performs no discovery or replay.

The separate fixture-directory exporter accepts at most 100,000 explicit
portable fixture IDs, writes canonical semantic JSON at
`fixtures/<fixture-id>.json`, and publishes a canonical
`evidence.fixture-index/1` sorted by fixture ID with exact byte hashes and sizes.
It reuses existing artifact, aggregate, path, and atomic-publication ceilings;
directory enumeration, clock, randomness, environment, and host paths do not
affect identity. This resolution adds no CLI, provider, execution authority,
version change, or Phase 3.7 work.

## 26. Phase 3.7 implementation resolution

The separately authorized 3.7 checkpoint adds exactly three local top-level CLI
commands after the frozen original nine: `export`, `verify`, and `migrate`.
`export SOURCE DESTINATION` validates the canonical `bundle.json` beneath an
explicit bundle root and delegates unchanged-byte atomic publication to the
accepted evidence exporter. `verify BUNDLE` delegates bounded, non-mutating
index, filesystem, size, hash, relationship, and identity validation to the
accepted evidence reader. Neither operation executes child artifacts.

`migrate SOURCE DESTINATION` requires explicit artifact kind, source schema,
product version, lowercase source SHA-256, and target contract. It first uses the
accepted planner and permits only a planned lossless route before delegating to
the closed 3.6 executor. Optional `--dry-run` emits the accepted canonical
`evidence.migration-plan/1` and creates no destination. Successful machine output
uses existing canonical JSON conventions; human output is compact and stable.
Existing exit integers are unchanged: evidence contract/integrity/migration
failures map to validation, unsafe/bounded filesystem input maps to security or
bound, and destination/publication failures map to I/O.

Fixture-directory CLI export is deferred because 3.6 exposes typed in-memory
declarations but no accepted serialized declaration format; no new input schema
is invented. The package-root API, `scenario_engine.cli` exports, console script,
dependencies, versions, all persisted schemas, and the original nine command
contracts remain unchanged. These commands perform no adapters, provider
discovery, network, subprocess, environment reads, semantic clock, randomness,
dynamic loading, replay, or execution. Phase 3.8 remains unstarted.
