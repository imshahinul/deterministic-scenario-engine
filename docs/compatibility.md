# Scenario Engine 1.0 compatibility contract

This document is normative for the frozen DSL, deterministic result, manifest,
and plugin contracts. It is not distribution or release metadata.

## Version roles

`ENGINE_VERSION` is the engine compatibility/replay contract version recorded
in every `ReproducibilityManifest`; it is not presently the distribution
version. Phase 1.0E must decide whether those versions become identical.

Engine SemVer has these meanings:

* **Major:** breaks a public API, accepted DSL, result schema, manifest schema,
  replay gate, or deterministic semantic contract.
* **Minor:** adds backward-compatible behavior or a newly and explicitly
  versioned deterministic algorithm.
* **Patch:** makes backward-compatible corrections without silently changing
  deterministic bytes inside the documented contract. A correctness or
  security correction that must change such bytes requires an explicit
  compatibility/version response.

## DSL 1.0

DSL version 1 is the integer `1`, never a boolean. Unknown fields are errors.
Accepted syntax, defaults, order, and types are not silently reinterpreted;
breaking changes require a new DSL version and/or major engine contract.

Parsing uses safe YAML construction. Duplicate mapping keys at every depth,
aliases, merge keys, arbitrary tags, floats as semantic values, and non-string
semantic mapping keys are rejected. Plain `true` and `false` are booleans;
legacy YAML 1.1 words (`yes`, `no`, `on`, `off`) are strings. Decimal integer
syntax is accepted; ambiguous legacy integer forms are strings. Standard null
spellings resolve to null. Semantic decimal, datetime, duration, and missing
values use their explicit typed wrappers.

Arithmetic operators accept only integers (excluding booleans) and finite
`Decimal` values. Addition, subtraction, and multiplication return an integer
for two integer operands and a `Decimal` if either operand is decimal. Division
always returns `Decimal`; division by zero is an expression error. Decimal
operations use precision 28 with round-half-even and never the caller's ambient
decimal context. Strings, lists, booleans, null, missing, duration, and arbitrary
Python operator overloads are not arithmetic operands.

Optional empty-container behavior remains compatibility-frozen: `validators`,
`invariants`, and `faults` may be empty; `resources`, `constraints`, and
`subflows` may not be explicitly empty. Empty `oracle.expected.constraints` and
`oracle.expected.invariants` collections are accepted.

## Result and manifest

`ScenarioResult` required stable normalized top-level fields are `artifacts`,
`clock`, `history`, `manifest`, `next`, `scenario_id`, `state`, and
`terminal_transition`. `provenance` is optional stable and appears only when it
has records. `next` is retained as a compatibility alias and is always identical
to `terminal_transition`. Runner, resources, and snapshot backing fields are
internal and not separately serialized.

Artifact fields are `address`, `id`, `name`, `type`, and `value`. History fields
are `address`, `artifacts`, `faults_applied`, `patch`, `post`, `pre`, `timestamp`,
and `transition`. Addresses are canonical JSON strings. Provenance and manifest
records use their normalized public mappings. Canonical result bytes are UTF-8,
semantic normalization, sorted keys, compact comma/colon separators, and no
trailing newline.

The stable manifest fields are `root_seed`, `scenario_canonical_hash`,
`engine_version`, `dsl_version`, `input_resource_hashes`,
`domain_pack_versions`, `generator_versions`, `rng_algorithm_version`,
`id_algorithm_version`, `locale`, `reference_clock_start`, and `run_index`.
Mappings normalize in key order. `domain_pack_versions` is reserved and must be
empty; replay rejects it otherwise. All other fields are active execution
coordinates or compatibility gates. A future additive field needs explicit
default and reader rules; unknown data is not silently treated as compatible.

Exact replay requires a compatible recorded engine contract, DSL version,
RNG/ID and generator/plugin algorithm versions, canonical scenario hash,
input/resource hashes, root seed, run index, locale, reference clock, and other
explicit execution context. The current engine requires exact `ENGINE_VERSION`
and exact compatibility-tuple matches. Unsupported cross-version replay fails
explicitly; indefinite replay across incompatible future major versions is not
promised.

## Plugins

A plugin name identifies a generator family. Its version is an exact,
immutable deterministic algorithm-contract identifier and is recorded under
`plugin:<name>` in `generator_versions`. Behavior-changing implementations must
use another version. Replay requires an explicitly registered compatible name
and version; unavailable or incompatible versions fail and are never silently
substituted. Package-release and deterministic-algorithm versions may differ.
There is no discovery, migration, network retrieval, or global registry contract.
