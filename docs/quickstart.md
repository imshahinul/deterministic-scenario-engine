# Quickstart

This guide runs the canonical cart history without optional dependencies. The
installed `scenario` console entry point is available in this Phase 2-capable
source tree; `--json` is a global option and therefore precedes the command.

## 1. Install

Install the package:

```console
python3 -m pip install deterministic-scenario-engine
```

To install from a source checkout instead, run from the repository root:

```console
python3 -m venv /tmp/scenario-engine-quickstart
/tmp/scenario-engine-quickstart/bin/python -m pip install .
```

## 2. Read the DSL document

[`examples/cart.yaml`](../examples/cart.yaml) creates a cart, adds one generated
item, and checks out. It demonstrates typed decimal values, logical IDs,
addressed integers, derivation, shallow writes, artifacts, and logical time.

## 3. Parse, compile, execute, and replay

Save this as `/tmp/scenario_engine_quickstart.py`, or run it in a Python session
whose working directory is the repository root:

```python
from pathlib import Path

from scenario_engine import (
    ReproducibilityManifest,
    ScenarioResult,
    compile_document,
    parse_yaml,
    replay_scenario,
    run_scenario,
)

yaml_text = Path("examples/cart.yaml").read_text(encoding="utf-8")

# Parsing checks the YAML source contract and DSL schema.
document = parse_yaml(yaml_text)

# Compilation resolves expressions and the executable step graph.
compiled = compile_document(document)

# The root seed and nonnegative run index are explicit execution coordinates.
result = run_scenario(compiled, root_seed="quickstart", run_index=0)
assert isinstance(result, ScenarioResult)

# Read current logical state through the supported result property.
state = result.final_state
assert state["checkout_complete"] is True
assert len(state["cart_items"]) == 1

# History contains committed steps; artifacts are declarations emitted by them.
assert len(result.history.records) == 3
assert [artifact.artifact_type for artifact in result.artifacts] == [
    "cart_created",
    "cart_item_added",
    "cart_checked_out",
]

# Stable bytes include normalized state, history, artifacts, clock, and manifest.
stable_bytes = result.to_json_bytes()
assert stable_bytes == result.to_json_bytes()

manifest = result.manifest
assert isinstance(manifest, ReproducibilityManifest)

# Replay re-parses and checks compatibility before running the recorded context.
replayed = replay_scenario(yaml_text, manifest)
assert replayed.to_json_bytes() == stable_bytes

print(result.final_state)
print(result.trace())
print(stable_bytes.decode("utf-8"))
```

Run it with the isolated environment:

```console
/tmp/scenario-engine-quickstart/bin/python /tmp/scenario_engine_quickstart.py
```

`ScenarioResult.normalized()["state"]` is the stable serialized state field.
The convenient Python property is `ScenarioResult.final_state`; there is no
top-level `ScenarioResult.state` attribute in the frozen public API.

For inputs/resources, continue with [`examples/resources.yaml`](../examples/resources.yaml)
and the [DSL reference](dsl-reference.md). For replay guarantees and limits, see
[reproducibility](reproducibility.md) and [compatibility](compatibility.md).

## 4. Phase 2 CLI path

Run these from a source checkout after installation. Every source is an explicit
local file, and every execution supplies its deterministic seed coordinate.

```console
scenario validate examples/cart.yaml
scenario --json hash examples/cart.yaml
scenario --json run examples/cart.yaml --seed quickstart --run-index 0 > /tmp/dse-result.json
scenario --json inspect /tmp/dse-result.json --kind result
scenario --json diff /tmp/dse-result.json /tmp/dse-result.json --kind result --mode first
scenario --json matrix examples/cart.yaml --seed quickstart --dimensions '[{"name":"region","values":["us","eu"]}]' --describe
```

The diff exits 0 because the artifacts are equal. A valid unequal diff exits 1.
For replay, batch-plan syntax, all flags, stdout/stderr rules and hard bounds,
use the [Phase 2 public contract](phase2-public-contract.md#cli-contract).
