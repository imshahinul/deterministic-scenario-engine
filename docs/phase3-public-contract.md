# Phase 3 Public Contract Freeze

## 1. Scope and thesis

This document is the normative additive contract for the implemented but
unreleased Phase 3 evidence-interchange line. It makes deterministic evidence
portable without changing the frozen execution engine. Version 2.0.0 is already
published; the eventual Phase 3 distribution target is 2.1.0, which is not
published and has no release candidate at this checkpoint.

Phase 3 adds no package-root exports, execution semantics, DSL syntax, dependency,
or automatic discovery. The historical [Phase 2 contract](phase2-public-contract.md)
continues to govern suite generation, composition, matrix, batch, inspection,
diff, Domain Packs, Oracle Assertions, and the original nine CLI commands.

## 2. Stable public imports

`scenario_engine.__all__` remains the 33-name stable root. Phase 3 APIs are
explicit subpackage APIs. Every name in an intentional `__all__` is supported at
that package import path; importable helpers outside these manifests are
intentionally internal.

```text
scenario_engine count=33
scenario_engine sha256=f19f9c8ebe3fd5574550fea1fdefc5a20fa004a4913978e8bf5ab1e447278a50
scenario_engine.suite count=44
scenario_engine.suite sha256=7db8a4edf260d1d16960203dfa43672d1d9cb8e4eed1624be87a9201ded59512
scenario_engine.composition count=29
scenario_engine.composition sha256=689f1fecb3bbbe4822ce523e09084857f9da625a31b4b1e9bbc447d3bc425fe7
scenario_engine.matrix count=25
scenario_engine.matrix sha256=90611e656a435284db4b92dac84e1aa4d6b55b5a2172094ed3fa8598c86f15b3
scenario_engine.batch count=32
scenario_engine.batch sha256=59876678a4f4349a66b6caff4583e3cf8eb02425e3c7fc2b47d047edab1ad834
scenario_engine.inspection count=33
scenario_engine.inspection sha256=3019b2a100afc8db8cb3272d38e24459be9929f785b6a6cf0c4c1a6bfb7f63ab
scenario_engine.diff count=24
scenario_engine.diff sha256=281136c0d1ba298a2be91344be9a9b1f380d3519e2c18f05b7ad8383470c3c0e
scenario_engine.cli count=2
scenario_engine.cli sha256=28361a19b5501e0631da3e10a8fa676b6aa37d7ab0e1faf54e5a5bc4b3f186a3
scenario_engine.domain_packs count=14
scenario_engine.domain_packs sha256=d62dec3381ceba87d6f1231304b9b21779d0570171cba40b7905615cea8e7a6a
scenario_engine.oracle_assertions count=25
scenario_engine.oracle_assertions sha256=bf3b83ed474567f02b6d796fce898e13f766740b599bb69f7258ca7e95514dc6
scenario_engine.evidence count=95
scenario_engine.evidence sha256=4b3f258c47ea896d4455fb56262b415d6dfeaa7a791a59e23d94349171f8cb7b
scenario_engine.reference_packs count=4
scenario_engine.reference_packs sha256=9b81eb1663ef5da3215de5fd93f47e96bb76be4305d3fb5c33376f5220a44c01
```

The hash rule is SHA-256 of the LF-joined sorted `__all__` names. Root names are
`PUBLIC_STABLE`; names exported by the listed specialized packages are
`PUBLIC_SUBPACKAGE`; all other importable implementation symbols are
`INTENTIONALLY_INTERNAL` unless another frozen contract says otherwise.

The Phase 3 evidence surface comprises the immutable `EvidenceBundle`,
`EvidenceEntry`, `EvidenceRelationship`, and `EvidenceProvenance` families;
canonical evidence serializers and identity; safe reader and exporters;
`EvidenceAdapter` capability/publication/receipt contracts; `ArtifactDescriptor`,
compatibility report and migration-plan families; migration execution result;
fixture declarations/index/export; their constants; and their exact specialized
errors. `scenario_engine.reference_packs` exports exactly
`EcommerceEvidenceWorkflow`, `ecommerce_domain_pack`, `ecommerce_registry`, and
`export_ecommerce_evidence`.

## 3. Evidence schemas

The persisted Phase 3 schema inventory is exactly:

```text
evidence.bundle/1
evidence.entry/1
evidence.relationship/1
evidence.provenance/1
evidence.adapter-capability/1
evidence.adapter-receipt/1
evidence.compatibility-report/1
evidence.migration-plan/1
evidence.fixture-index/1
```

Phase 2 schemas remain `suite.artifact-read/1`, `suite.run/1`,
`suite.manifest/1`, `matrix.case/1`, `suite.matrix/1`, `batch.plan/1`,
`suite.batch/1`, `composition.modules/1`, `matrix.plan/1`,
`inspection.document/1`, `inspection.explanation/1`, `semantic.diff/1`,
`domain-pack/1`, `oracle.assertion/1`, and `oracle.evaluation/1`.
`MigrationExecutionResult` has canonical serialization but is not a separately
versioned persisted schema.

## 4. Canonicalization

Canonical model bytes are compact UTF-8 JSON with sorted mapping keys, preserved
Unicode, no non-finite numbers, and no trailing newline. Entries and relationships
use deterministic model ordering. `bundle_id` is the SHA-256 of canonical bundle
index bytes. Artifact content hashes cover exact bytes; destination paths and
filesystem enumeration never become identity. Canonical JSONL preserves record
order and emits one canonical value plus LF per record.

## 5. Safe reader

`read_evidence_bundle()` accepts an explicit local directory and validates the
canonical `evidence.json` index, exact canonical bytes, schemas, path shape,
entry/relationship counts, depth, declared sizes, aggregate size, regular-file
status, links, and SHA-256. It neither executes nor replays child artifacts and
does not evaluate Oracle Assertions. Future or unknown schemas fail closed.

## 6. Export

`canonical_evidence_records_bytes()` and `write_evidence_jsonl()` provide bounded
canonical record export. `export_evidence_bundle()` verifies declared local
source bytes and atomically publishes a canonical bundle to an explicit absent
destination. It does not overwrite, discover inputs, retrieve remote artifacts,
or execute evidence.

## 7. Adapter contract

Adapters are explicit caller-supplied Python objects implementing the public
`EvidenceAdapter` contract. Capability and receipt schemas are versioned;
publication has deterministic ordinal ordering and bounded in-flight work.
There is no adapter/provider discovery. Adapters are trusted, unsandboxed, and
own their external side effects; core orchestration remains bounded and records
only declared receipt outcomes.

## 8. Compatibility capabilities

The finite vocabulary, in order, is:

```text
READABLE
INSPECTABLE
DIFFABLE
EXECUTABLE
REPLAYABLE
MIGRATABLE
UNSUPPORTED
```

Readability does not imply execution; inspection does not imply replay. Evidence
bundles do not execute children, and reading Oracle evidence does not execute
assertions. Supported v1 result/manifest artifacts are readable, inspectable,
diffable, and migratable through their frozen wrapper routes, but legacy v1
execution replay remains unsupported. Supported v2 artifacts follow the finite
source table and require all recorded coordinates before execution or replay is
reported. Unknown/future schemas and product majors fail closed. Migration is
reported only for a known provably lossless route.

## 9. Migration

`plan_migration()` is metadata-only and non-executing. There is no route
discovery, dynamic loading, recursive chain, or data-supplied callable. Plans
contain at most 1,000 steps; executable routes are currently exactly one step.
The six executable transformation IDs are:

```text
wrap-v1-manifest-as-evidence/1
wrap-v1-result-as-evidence/1
wrap-v2-batch-as-evidence/1
wrap-v2-composition-as-evidence/1
wrap-v2-matrix-as-evidence/1
wrap-v2-suite-as-evidence/1
```

`execute_lossless_migration()` accepts only the closed internal map, verifies the
source SHA-256, requires an explicit regular-file source and absent destination,
leaves the source untouched, preserves exact source bytes in the wrapper bundle,
and produces deterministic target and execution identities. No lossy route is
supported.

## 10. Fixture export

Fixture declarations require explicit stable IDs. `export_fixture_directory()`
creates deterministic local fixture paths and `evidence.fixture-index/1`, checks
hashes and bounds, and atomically publishes only to an absent destination. It
does not discover fixtures or overwrite existing output.

## 11. CLI

The console script remains `scenario = scenario_engine.cli:main`; module
execution is `python -m scenario_engine.cli`. `--json` is global and precedes the
command. Top-level commands are exactly:

```text
validate
run
replay
hash
inspect
explain
diff
matrix
batch
export
verify
migrate
```

The original nine retain the Phase 2 behavior. `export` validates and copies a
local bundle to an absent destination; `verify` validates a local bundle;
`migrate` plans or executes a frozen lossless wrapper route, with `--dry-run`
remaining non-writing. Successful payloads use stdout; bounded diagnostics use
stderr without traceback. Exit codes are:

```text
SUCCESS=0
DIFFERENT=1
USAGE=2
VALIDATION=3
EXECUTION=4
REPLAY_COMPATIBILITY=5
SECURITY_OR_BOUND=6
IO=7
INTERNAL=8
```

## 12. Ecommerce reference workflow

The demonstrator identity is `ecommerce.reference_evidence@1`; its Domain Pack
SHA-256 is `987651d083d7c87696ef10c377080e08a173a56bd64aa6114262e5f6e0c35bb6`
and evidence bundle ID is
`db145c19d041ffbed668404a8945604e735d9db42c8f75068d657ba4a0c4c507`.

It demonstrates Domain Pack → explicit ecommerce plugins → execution → replay →
inspection → Oracle Assertions → semantic diff → evidence bundle → CLI
verify/export. `export_ecommerce_evidence()` is a fixed bounded demonstrator,
not a generic workflow or pipeline abstraction. Phase 3.9 was skipped because
this evidence demonstrated no additional gap.

## 13. Bounds

MiB means 1,048,576 bytes and GiB means 1,073,741,824 bytes.

| Phase 3 area | Bound |
|---|---:|
| Bundle entries | 100,000 |
| Bundle relationships | 100,000 |
| Bundle canonical index | 16 MiB |
| Individual artifact | 256 MiB |
| Default aggregate bundle | 256 MiB |
| Hard aggregate bundle | 4 GiB |
| Bundle path depth | 64 |
| Bundle index depth | 64 |
| JSONL records | 100,000 |
| Adapter default / hard in-flight | 64 / 1,024 |
| Adapter receipt / aggregate receipts | 1 MiB / 16 MiB |
| Fixtures | 100,000 |
| Compatibility requirements | 64 |
| Migration steps | 1,000; recursive migration forbidden |

Inherited Phase 2 ceilings remain normative in the [Phase 2 contract](phase2-public-contract.md#hard-bounds).

## 14. Security and trust boundary

Core evidence input is untrusted. Processing is local, bounded, non-executing,
and has no network, provider discovery, environment-driven semantics, random
semantics, or wall-clock semantics. Paths are relative POSIX children; traversal,
links, symlinks, special files, and unsafe destinations fail closed. Publication
is explicit, no-overwrite, and atomic.

Explicit Python plugins, Domain Packs, and adapter objects are trusted and not
sandboxed. Migrations use a closed internal transformation map with no dynamic
import or arbitrary callable from artifacts.

## 15. Version strategy

```text
current source distribution version=2.0.0
eventual Phase 3 release target=2.1.0
ENGINE_VERSION=1.0.0
manifest.engine_version=1.0.0
DSL=1
```

Phase 3.11 performs no version bump. Distribution, engine, manifest, and DSL
versions have separate meanings. Packaging and an authorized 2.1.0 bump belong
only to Phase 3.12.

## 16. Backward compatibility

The 33-name package root, Phase 2 subpackage manifests, result/manifest bytes,
DSL 1, engine compatibility token, dependencies, and original CLI behavior are
unchanged. Evidence APIs remain under explicit subpackages. Compatibility is a
finite capability report, not a promise of indefinite incompatible cross-major
replay.

## 17. Explicit non-goals

Phase 3 does not provide a distributed scheduler/workers/service, remote artifact
retrieval in core, automatic plugin/Domain Pack/adapter/provider discovery,
arbitrary Python or query execution from evidence, recursive or lossy migration,
indefinite incompatible cross-major replay, automatic Schemathesis HTTP
execution, DB/ORM-owned `ScenarioState`, a raw SQL DSL, hidden randomness,
ambient environment semantics, hidden wall-clock semantics, or a generic
workflow/pipeline framework.

## 18. Release state

Versions 1.0.0 and 2.0.0 are published. Phase 3 implementation is on `main`, but
2.1.0 is not published and no Phase 3 release candidate exists. Phase 3.11 is a
contract/documentation freeze, not a release. Phase 3.12 has not started.
