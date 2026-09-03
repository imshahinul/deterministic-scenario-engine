# Deterministic Scenario Engine

**Generate test scenarios, not just test records.**

Deterministic Scenario Engine creates reproducible, state-consistent business
histories with deterministic ground truth for testing.

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

Core execution does not require a database, network service, plugin, or property
testing framework. See [security assumptions and non-goals](docs/security-and-non-goals.md).

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

These are local-source commands, not a claim that a public package exists. The
local, unpublished release-candidate distribution is
`deterministic-scenario-engine` 1.0.0. After a future publication, the intended
package command will be `pip install deterministic-scenario-engine`, with extras
such as `pip install 'deterministic-scenario-engine[pytest]'`. It is not currently
available from PyPI; release-candidate validation installs locally built artifacts.

## Minimal quickstart

The public [cart scenario](examples/cart.yaml) is an executable DSL 1 document.
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
Unsupported cross-version replay fails explicitly. See the [determinism model](docs/determinism.md),
[reproducibility guide](docs/reproducibility.md), and normative
[compatibility contract](docs/compatibility.md).

## Documentation

- [Quickstart](docs/quickstart.md)
- [DSL 1 reference](docs/dsl-reference.md)
- [Determinism model](docs/determinism.md)
- [Reproducibility and replay](docs/reproducibility.md)
- [Testing, faults, and oracle](docs/testing-oracle.md)
- [Plugins](docs/plugins.md)
- [SQLAlchemy adapter](docs/sqlalchemy.md)
- [Hypothesis integration](docs/hypothesis.md)
- [Schemathesis integration](docs/schemathesis.md)
- [Public Python API](docs/api.md)
- [Security assumptions and non-goals](docs/security-and-non-goals.md)
- [Compatibility contract](docs/compatibility.md)

## Status

This repository represents the frozen, unpublished local 1.0 release candidate.
Its distribution and engine compatibility version are both 1.0.0, and it is
licensed under Apache-2.0. It has not been published to PyPI or any Git host.
