# Reproducibility and replay

This guide is subordinate to the normative [compatibility contract](compatibility.md).

## ScenarioResult

`run_scenario()` returns a `ScenarioResult`: a frozen snapshot of current state,
committed `ScenarioHistory`, artifacts, logical clock, terminal transition,
manifest, and—when present—provenance. `to_json_bytes()` provides canonical
observable result bytes.

The stable normalized result schema has required top-level fields:

- `artifacts`
- `clock`
- `history`
- `manifest`
- `next`
- `scenario_id`
- `state`
- `terminal_transition`

`provenance` is optional and appears only when records exist. `next` is retained
as an exact compatibility alias of `terminal_transition`; they are always equal.

Canonical result bytes are UTF-8 JSON after semantic normalization, with sorted
mapping keys, compact comma/colon separators, Unicode preserved, and no trailing
newline. Decimal, datetime, duration, `LogicalID`, and `MISSING` values use the
engine's stable normalized forms.

## ReproducibilityManifest

The manifest records:

- root seed and nonnegative run index;
- canonical scenario hash and DSL version;
- hashes of consumed external inputs and resolved resources;
- locale and aware reference-clock start;
- engine compatibility version;
- addressed RNG and logical-ID algorithm versions; and
- built-in generator plus exact plugin algorithm versions.

`domain_pack_versions` is currently reserved-empty and replay rejects a nonempty
value. Plugin versions appear as `plugin:<name>` in `generator_versions`.

Canonical scenario hashing operates on the parsed semantic scenario, not YAML
formatting. Formatting-only equivalent source therefore hashes identically.
Resource hashes cover resolved resources and consumed input values. Unused
external input keys are not consumed and do not affect result or manifest bytes.

## Exact replay

```python
from pathlib import Path
from scenario_engine import compile_document, parse_yaml, replay_scenario, run_scenario

text = Path("examples/cart.yaml").read_text(encoding="utf-8")
result = run_scenario(compile_document(parse_yaml(text)), "replay-guide")
replayed = replay_scenario(text, result.manifest)
assert replayed.to_json_bytes() == result.to_json_bytes()
```

Exact replay requires a compatible recorded execution contract: scenario hash,
inputs/resources, root seed, run index, locale, reference clock, engine/DSL
versions, RNG/ID algorithms, and generator/plugin versions must pass replay
gates. A plugin scenario also needs the explicitly constructed compatible
registry and the same explicit inputs.

Unsupported cross-version replay fails explicitly with
`ReplayCompatibilityError`. Indefinite replay across incompatible future major
contracts is not promised.

## Frozen compatibility examples

With the frozen test execution coordinates, canonical result SHA-256 values are:

- cart: `ea85ecfe3d6014f10481637db4e8a137d00ffab0bdcfe4ed070f0b1404ee123e`
- structured control flow: `73de01131fa12f904dee388a5ba04d11f8001ddde2a6d6b94e10b0ded0a75c61`
- oracle/provenance: `cd28c9fdadef67267aa7f0dc950dd5d19331dc30c3d84636d0c678f481ac16b8`

These are regression anchors, not promises that arbitrary future incompatible
engine contracts will replay them.
