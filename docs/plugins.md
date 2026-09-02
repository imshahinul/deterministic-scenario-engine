# Deterministic generator plugins

Plugins extend value generation at an explicit trust and compatibility boundary.
They do not redesign DSL execution.

## Architecture

`GeneratorPlugin(name, version, generate)` associates a lowercase namespaced
name and exact nonempty algorithm-contract version with a Python callable. The
callable receives:

```python
def generate(context: PluginGenerationContext, arguments):
    ...
```

`PluginGenerationContext` exposes only addressed deterministic services:

- `rng` — RNG bound to the generator's execution address;
- `ids` — deterministic logical-ID provider;
- `clock` — the explicit logical clock; and
- `address` — the complete `ExecutionAddress`.

Arguments are evaluated explicitly from DSL expressions and recursively isolated
before invocation. Returned values must fit the engine semantic value model.

Build a `PluginRegistry` explicitly and pass it to execution and replay. Registry
iteration order is not semantic. A DSL declaration selects exact `name` and
`version`:

```yaml
customer_email:
  $plugin:
    name: ecommerce.customer_email
    version: "1"
    args:
      domain: {$resource: email_domain}
      prefix: {$literal: shopper}
```

Required plugins are prevalidated. The manifest records each as
`plugin:<name>: <version>` in `generator_versions`. Replay requires the explicit
registry to contain the same names and exact versions. A behavior-changing
implementation must use a new algorithm-contract version; it must never silently
replace behavior behind an existing name/version.

## Trust and isolation

**Plugins are Python code and are not sandboxed.** Register only trusted code.
A plugin must obey the deterministic contract and use its supplied services and
arguments rather than ambient state.

There is no:

- automatic global registration;
- YAML dynamic import;
- Python entry-point discovery;
- filesystem scanning;
- network retrieval;
- hidden random source; or
- hidden wall clock.

## Ecommerce reference pack

The repository includes an advanced reference/example pack. Importing it does
not register anything. The factory returns a fresh explicit registry containing
four version-`"1"` generators.

```python
from pathlib import Path

from scenario_engine import compile_document, parse_yaml, replay_scenario, run_scenario
from scenario_engine.reference_packs.ecommerce import ecommerce_registry

text = Path("examples/ecommerce.yaml").read_text(encoding="utf-8")
registry = ecommerce_registry()
inputs = {"email_domain": "example.test"}

scenario = compile_document(parse_yaml(text))
result = run_scenario(
    scenario,
    root_seed="plugin-guide",
    inputs=inputs,
    plugins=registry,
)
assert result.final_state["status"] == "shipped"
assert result.manifest.generator_versions["plugin:ecommerce.sku"] == "1"

replayed = replay_scenario(
    text,
    result.manifest,
    inputs=inputs,
    plugins=ecommerce_registry(),
)
assert replayed.to_json_bytes() == result.to_json_bytes()
```

This pack is reference/example functionality, not an implicit core service.
See [compatibility](compatibility.md) and [security](security-and-non-goals.md).
