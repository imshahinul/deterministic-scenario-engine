# Deterministic Scenario Engine

**Generate test scenarios, not just test records.**

Deterministic Scenario Engine (DSE) creates reproducible, state-consistent
business histories and deterministic scenario suites with ground truth for
testing. The source-tree distribution version is 2.2.0. Distribution release
identity and deterministic compatibility identity are separate:
`ENGINE_VERSION` remains 1.0.0 and DSL version remains 1. For authoritative
public-release availability and history, see PyPI and GitHub Releases.

## Why it exists

Fake-data libraries and random record generators produce values; fixtures often
describe isolated records. Scenario Engine executes histories: each committed
step sees a consistent state, produces traceable state changes and artifacts,
and advances an explicit logical clock. The same scenario and execution context
can be replayed byte-for-byte, while invariants, controlled faults, and an oracle
make expected behavior explicit.

## Core capabilities

- DSL 1 parsing, compilation, and deterministic execution
- addressed randomness and logical IDs that do not depend on a shared stream
- current state plus append-only committed history and artifacts
- whole-step atomicity
- explicit external inputs, resource DAG resolution, validators, and constraints
- subflows, ordered branches, and bounded repeat
- invariants, deterministic fault injection, provenance, and oracle evaluation
- canonical result bytes and a `ReproducibilityManifest` for exact replay
- an explicit, versioned plugin boundary and a reference ecommerce plugin pack
- a JSON-file adapter
- optional pytest, SQLAlchemy Core, Hypothesis, and Schemathesis integrations
- secure, explicit local-file composition with namespaced modules
- ordered Cartesian matrices with stable case IDs and original indexes
- immutable ordered batch plans and worker-independent results
- structured, redacted inspect/explain evidence and typed RFC 6901 semantic diff
- validated scenario-definition structural diff with canonical semantic addresses
- self-contained, deterministic offline HTML trace views of local result evidence
- `scenario` CLI for local and CI workflows, including bounded
  local evidence export, verification, and lossless migration
- explicit immutable Domain Pack registries and pure Oracle Assertions
- canonical evidence bundles, ordered JSON/JSONL export, compatibility reports,
  explicit adapters, closed lossless migrations, and fixture-directory export

Release 2.2.0 adds first-class run → replay artifacts and fail-closed replay
diagnostics, actionable human and machine-readable errors, author-time
scaffolding, scenario-definition diff, conservative impact analysis, offline
trace views, and an installed compatibility-fixture export. See the
[2.2.0 release notes](https://github.com/imshahinul/deterministic-scenario-engine/blob/main/docs/release-notes-2.2.0.md).

Core execution does not require a database, network service, plugin, or property
testing framework. See [security assumptions and non-goals](https://github.com/imshahinul/deterministic-scenario-engine/blob/main/docs/security-and-non-goals.md).
Neither Phase 2 nor Phase 3 adds hidden discovery, network, randomness,
wall-clock, or ambient environment semantics. The historical Phase 2 contract
is frozen in the [Phase 2 public contract](https://github.com/imshahinul/deterministic-scenario-engine/blob/main/docs/phase2-public-contract.md); the
additive evidence surface is frozen in the [Phase 3 public contract](https://github.com/imshahinul/deterministic-scenario-engine/blob/main/docs/phase3-public-contract.md).

## Installation

Supported Python versions are 3.11, 3.12, 3.13, and 3.14.

Install the published package and use its `scenario` entry point:

```console
python3 -m pip install deterministic-scenario-engine
scenario --help
```

Install only the named optional integrations you need:

```console
python3 -m pip install 'deterministic-scenario-engine[pytest]'
python3 -m pip install 'deterministic-scenario-engine[sqlalchemy]'
python3 -m pip install 'deterministic-scenario-engine[hypothesis]'
python3 -m pip install 'deterministic-scenario-engine[schemathesis]'
```

Installing the current checkout with `python3 -m pip install .` is a
source-development-only alternative.

## Minimal quickstart

The [canonical installed-package workflows](https://github.com/imshahinul/deterministic-scenario-engine/blob/main/docs/quickstart.md)
start by creating a complete portable DSL file under `/tmp/dse-demo`; they do
not require a source checkout or files from this repository. The guide covers
validate, run → replay, inspect/explain, both diff commands, conservative impact
analysis, export → verify, the static trace viewer, scaffold → validate, and the
human/machine diagnostic contract.

## Determinism contract

Generation derives from semantic `ExecutionAddress` values, not consumption of
a mutable global random stream. Exact replay requires the same canonical
scenario, explicit inputs, algorithms/plugins, and recorded execution context.
Unsupported cross-version replay fails explicitly. See the [determinism model](https://github.com/imshahinul/deterministic-scenario-engine/blob/main/docs/determinism.md),
[reproducibility guide](https://github.com/imshahinul/deterministic-scenario-engine/blob/main/docs/reproducibility.md), and normative
[compatibility contract](https://github.com/imshahinul/deterministic-scenario-engine/blob/main/docs/compatibility.md).

The installed public compatibility corpus can be discovered with
`scenario --help` and exported without a source checkout using
`scenario compatibility-fixtures export --out /absolute/path`.

## Canonical command workflows

Use the [quickstart](https://github.com/imshahinul/deterministic-scenario-engine/blob/main/docs/quickstart.md#canonical-installed-package-workflows)
as the single canonical workflow document. In particular, `scenario diff`
compares execution artifacts, while `scenario diff-definition` structurally
compares validated scenario definitions. `scenario impact` is a separate,
conservative static may-impact analysis. `scenario trace-view` creates one
self-contained offline HTML file from supported result/evidence.

## Documentation

- [Quickstart](https://github.com/imshahinul/deterministic-scenario-engine/blob/main/docs/quickstart.md)
- [DSL 1 reference](https://github.com/imshahinul/deterministic-scenario-engine/blob/main/docs/dsl-reference.md)
- [Determinism model](https://github.com/imshahinul/deterministic-scenario-engine/blob/main/docs/determinism.md)
- [Reproducibility and replay](https://github.com/imshahinul/deterministic-scenario-engine/blob/main/docs/reproducibility.md)
- [Testing, faults, and oracle](https://github.com/imshahinul/deterministic-scenario-engine/blob/main/docs/testing-oracle.md)
- [Plugins](https://github.com/imshahinul/deterministic-scenario-engine/blob/main/docs/plugins.md)
- [SQLAlchemy adapter](https://github.com/imshahinul/deterministic-scenario-engine/blob/main/docs/sqlalchemy.md)
- [Hypothesis integration](https://github.com/imshahinul/deterministic-scenario-engine/blob/main/docs/hypothesis.md)
- [Schemathesis integration](https://github.com/imshahinul/deterministic-scenario-engine/blob/main/docs/schemathesis.md)
- [Public Python API](https://github.com/imshahinul/deterministic-scenario-engine/blob/main/docs/api.md)
- [Security assumptions and non-goals](https://github.com/imshahinul/deterministic-scenario-engine/blob/main/docs/security-and-non-goals.md)
- [Compatibility contract](https://github.com/imshahinul/deterministic-scenario-engine/blob/main/docs/compatibility.md)
- [2.2.0 release notes](https://github.com/imshahinul/deterministic-scenario-engine/blob/main/docs/release-notes-2.2.0.md)
- [Phase 2 public contract, CLI, and hard bounds](https://github.com/imshahinul/deterministic-scenario-engine/blob/main/docs/phase2-public-contract.md)
- [Phase 3 public contract and evidence interchange](https://github.com/imshahinul/deterministic-scenario-engine/blob/main/docs/phase3-public-contract.md)

## Status

Distribution release identity and deterministic engine compatibility are
separate contracts. This source tree reports distribution version 2.2.0;
generated core manifests retain `ENGINE_VERSION` 1.0.0 and DSL 1. PyPI and
GitHub Releases are the authoritative sources for public-release availability
and history. The project is licensed under Apache-2.0.
