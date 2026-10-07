# Deterministic Scenario Engine

**Generate test scenarios, not just test records.**

Deterministic Scenario Engine (DSE) creates reproducible, state-consistent
business histories and deterministic scenario suites with ground truth for
testing. The source-tree distribution version is 2.1.2. Distribution release
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

Core execution does not require a database, network service, plugin, or property
testing framework. See [security assumptions and non-goals](https://github.com/imshahinul/deterministic-scenario-engine/blob/main/docs/security-and-non-goals.md).
Neither Phase 2 nor Phase 3 adds hidden discovery, network, randomness,
wall-clock, or ambient environment semantics. The historical Phase 2 contract
is frozen in the [Phase 2 public contract](https://github.com/imshahinul/deterministic-scenario-engine/blob/main/docs/phase2-public-contract.md); the
additive evidence surface is frozen in the [Phase 3 public contract](https://github.com/imshahinul/deterministic-scenario-engine/blob/main/docs/phase3-public-contract.md).

## Installation

From a source checkout, use a virtual environment and install the checkout:

```console
python3 -m venv /tmp/scenario-engine-docs-venv
/tmp/scenario-engine-docs-venv/bin/python -m pip install .
```

Install only the named optional integrations you need:

```console
/tmp/scenario-engine-docs-venv/bin/python -m pip install '.[pytest]'
/tmp/scenario-engine-docs-venv/bin/python -m pip install '.[sqlalchemy]'
/tmp/scenario-engine-docs-venv/bin/python -m pip install '.[hypothesis]'
/tmp/scenario-engine-docs-venv/bin/python -m pip install '.[schemathesis]'
```

Install the package with `pip install deterministic-scenario-engine`, or select
an optional integration with a command such as
`pip install 'deterministic-scenario-engine[pytest]'`.

## Minimal quickstart

The public [cart scenario](https://github.com/imshahinul/deterministic-scenario-engine/blob/main/examples/cart.yaml) is an executable DSL 1 document.
Run it from the repository root:

```python
from pathlib import Path

from scenario_engine import (
    compile_document,
    parse_yaml,
    replay_scenario,
    run_scenario,
)

yaml_text = Path("examples/cart.yaml").read_text(encoding="utf-8")
document = parse_yaml(yaml_text)
scenario = compile_document(document)
result = run_scenario(scenario, root_seed="quickstart", run_index=0)

print(result.final_state["checkout_complete"])
print(result.trace())
stable_bytes = result.to_json_bytes()
manifest = result.manifest

replayed = replay_scenario(yaml_text, manifest)
assert replayed.to_json_bytes() == stable_bytes
```

`ScenarioResult.final_state` is the supported state-reading property; the stable
normalized result contains the same data under its `state` field.

## Determinism contract

Generation derives from semantic `ExecutionAddress` values, not consumption of
a mutable global random stream. Exact replay requires the same canonical
scenario, explicit inputs, algorithms/plugins, and recorded execution context.
Unsupported cross-version replay fails explicitly. See the [determinism model](https://github.com/imshahinul/deterministic-scenario-engine/blob/main/docs/determinism.md),
[reproducibility guide](https://github.com/imshahinul/deterministic-scenario-engine/blob/main/docs/reproducibility.md), and normative
[compatibility contract](https://github.com/imshahinul/deterministic-scenario-engine/blob/main/docs/compatibility.md).

## Structural definition comparison

`scenario diff` compares recorded execution artifacts. The separate
`scenario diff-definition scenario-a.yaml scenario-b.yaml` command validates and
structurally compares two DSL 1 definitions without executing either one. Its
JSON result uses `scenario.definition-diff/1`; changed entities use canonical
`scenario.semantic-address/1` addresses rather than YAML paths.

Comments, whitespace, YAML mapping-key order, and equivalent serialization
layout produce zero changes. A real transition change is rendered as, for
example, `CHANGED scenario:/step/checkout/transition/target`. Ordered DSL 1
sequences remain ordered: emit order and control-flow branch case order are
compared as structure. Identifier-keyed declarations (steps, generators,
derives, writes, faults, invariants, constraints, validators, and resources) are
compared by identity; step list order is represented by validated transitions.
Renames are conservatively reported as removal plus addition. This command
reports structural changes only; it performs no impact analysis and makes no
behavioral-equivalence claim.

## Offline trace viewer

Run a scenario to a local result file, then render it without re-execution:

```console
scenario --json run examples/cart.yaml --seed demo > result.json
scenario trace-view /absolute/path/result.json --out /absolute/path/trace.html
open /absolute/path/trace.html
```

The output is exactly one self-contained `scenario.trace-view/1` HTML file. It
works offline through `file://`, requires no server, network, remote assets, or
telemetry, and is read-only: source evidence is never changed. The viewer shows
only facts present in the supported v1 result or `suite.run/1` artifact and never
reruns a scenario or reconstructs missing runtime state.

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
- [Phase 2 public contract, CLI, and hard bounds](https://github.com/imshahinul/deterministic-scenario-engine/blob/main/docs/phase2-public-contract.md)
- [Phase 3 public contract and evidence interchange](https://github.com/imshahinul/deterministic-scenario-engine/blob/main/docs/phase3-public-contract.md)

## Status

Distribution release identity and deterministic engine compatibility are
separate contracts. This source tree reports distribution version 2.1.2;
generated core manifests retain `ENGINE_VERSION` 1.0.0 and DSL 1. PyPI and
GitHub Releases are the authoritative sources for public-release availability
and history. The project is licensed under Apache-2.0.
