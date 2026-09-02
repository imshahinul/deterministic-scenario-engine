# Hypothesis integration

Install the optional integration from a local source checkout:

```console
python3 -m venv /tmp/scenario-engine-hypothesis
/tmp/scenario-engine-hypothesis/bin/python -m pip install '.[hypothesis]'
```

Hypothesis selects explicit nonnegative run indexes and explicit input mappings.
`scenario_cases()` then parses, compiles, and executes those choices through
Scenario Engine. Hypothesis does not replace addressed RNG, and Hypothesis's own
randomness is not part of `ReproducibilityManifest`. Shrinking operates on the
explicit Scenario Engine context—the run index and input mapping. Exact replay
remains `replay_scenario()` using the result manifest and selected inputs.

Supported submodule surface:

- `ScenarioHypothesisCase`
- `scenario_cases`
- `HypothesisIntegrationError`

## Executable strategy example

This uses the core resources example without a plugin:

```python
from pathlib import Path

from hypothesis import find, settings, strategies as st

from scenario_engine import replay_scenario
from scenario_engine.integrations.hypothesis import ScenarioHypothesisCase, scenario_cases

text = Path("examples/resources.yaml").read_text(encoding="utf-8")
strategy = scenario_cases(
    text,
    root_seed="hypothesis-guide",
    run_indexes=st.integers(min_value=0, max_value=3),
    inputs=st.fixed_dictionaries({
        "customer_id": st.just("customer-docs"),
        "maximum_quantity": st.integers(min_value=1, max_value=10),
    }),
)

case = find(
    strategy,
    lambda item: item.inputs["maximum_quantity"] >= 4,
    settings=settings(max_examples=30, database=None, deadline=None),
)
assert isinstance(case, ScenarioHypothesisCase)
assert case.inputs["maximum_quantity"] == 4

replayed = replay_scenario(
    case.yaml_text,
    case.result.manifest,
    inputs=dict(case.inputs),
)
assert replayed.to_json_bytes() == case.result.to_json_bytes()
```

Supplying `plugins=` is supported when the scenario requires an explicit
`PluginRegistry`. The case records the selected YAML text, root seed, run index,
isolated inputs, locale, registry reference, and result; these are composition
values, not additions to the canonical top-level API.
