# Phase 2 Public Contract Freeze

This document defines the upcoming Phase 2 / 2.0 public contract implemented in
this source tree. It is a development contract freeze, not a claim that 2.0.0 is
published. Distribution and engine metadata remain 1.0.0 until authorized RC
work. DSL version remains integer 1: composition, matrix, and oracle assertions
are additive and do not reinterpret valid v1 documents.

## Supported product surface

- **Suite/read models:** immutable versioned run, suite, matrix, batch, failure,
  compatibility and bounded historical-artifact models.
- **Composition:** deterministic depth-one named local modules beneath an
  explicit root, sorted alias resolution, canonical content identity, and secure
  path handling.
- **Matrix:** ordered Cartesian expansion (last dimension fastest), pure filters,
  stable case IDs, and original pre-filter indexes used as run indexes.
- **Batch:** explicit immutable ordered plans, isolated members, deterministic
  failures and plan-order output independent of worker count/scheduling.
- **Inspect/explain:** immutable read-only normalized evidence, unavailable
  labels rather than invention, and secret-prone values redacted by default.
- **Semantic diff:** typed comparison over normalized models, RFC 6901 paths,
  `first` or bounded `complete` mode, and deterministic prefix truncation.
- **CLI:** thin local-file orchestration for the nine commands below.
- **Domain Packs:** explicit immutable declarative bundles with exact name and
  version, canonical identity, declarative plugin requirements, and a
  caller-created immutable registry with deterministic resolution. There is no
  discovery, global registry, or pack dependency mechanism in this foundation.
- **Oracle Assertions:** pure post-result evaluation of `equal`, `not_equal`,
  `present`, `absent`, `count`, `ordered_subsequence`, `occurrence_count`,
  `transition_occurrence`, `transition_order`, and `logical_time` over RFC 6901
  targets normalized by inspection. Outcomes are pass/fail/unavailable;
  redacted or unavailable evidence is not guessed. Evaluation never reruns or
  replays the scenario.

Stable APIs are package-root names listed in [API documentation](api.md) and
names in `__all__` of `scenario_engine.suite`, `.composition`, `.matrix`,
`.batch`, `.inspection`, `.diff`, `.cli`, `.domain_packs`, and
`.oracle_assertions`. Specialized Phase 2 APIs deliberately remain under these
subpackages. Importable helpers not in those manifests are intentionally
internal. Existing v1 root names are neither removed nor renamed.

## CLI contract

The console script is `scenario = scenario_engine.cli:main`; the pytest plugin
entry point is `scenario_engine = scenario_engine.pytest_plugin`. The public
commands are exactly:

```text
scenario validate
scenario run
scenario replay
scenario hash
scenario inspect
scenario explain
scenario diff
scenario matrix
scenario batch
```

Global JSON syntax is `scenario --json COMMAND ...` (before the command).
Human output is default. JSON mode writes one canonical UTF-8 JSON value and LF
to stdout. Successful payloads use stdout only; bounded safe diagnostics use
stderr only, without traceback. Identical explicit inputs produce byte-identical
machine output; timing, progress, color, host paths and worker completion order
are excluded.

Exit codes are stable: 0 success/equal, 1 valid different/oracle mismatch, 2
usage/input source, 3 parse/schema/compile/validation, 4 execution/oracle, 5
replay compatibility, 6 security/bound, 7 I/O, and 8 unexpected internal error.
Sources are explicit local regular files or `-`; at most one source may consume
stdin. URI/network sources are forbidden. Composition from stdin needs explicit
`--root`. Execution requires explicit `--seed`; run index defaults to 0 and
locale to `C`. Use `scenario COMMAND --help` for exact accepted flags.

For CI: validate explicit roots, hash definitions, run with explicit seed,
inputs and limits, preserve canonical artifacts, inspect failures, verify replay
compatibility, and semantic-diff approved artifacts. Compare JSON/hashes, not
terminal text; no CI-provider environment semantics enter the engine.

## Compatibility and replay

Supported v1 artifacts may be boundedly read, inspected, and semantically diffed
with v1 or Phase 2 artifacts through normalized read models. Those operations
never execute scenarios or load plugins. Phase 2 does not promise a complete
embedded v1 execution engine or indefinite incompatible cross-major execution
replay. Unsupported execution replay fails explicitly; use the frozen compatible
engine installation for exact v1 execution. See [compatibility](compatibility.md).

## Hard bounds

MiB means 1,048,576 bytes. These limits are public deterministic safety
contracts and are checked against source constants.

| Area | Bound |
|---|---|
| Composition | 64 modules; depth 1; 1 MiB root; 1 MiB/module; 16 MiB aggregate input; 16 MiB canonical composed payload |
| Matrix | 16 dimensions; 1,000 values/dimension; 100,000 raw Cartesian cases; 10,000 retained cases |
| Batch | 10,000 requests; 64 workers; 64 max in-flight; 256 MiB default retained-result bytes |
| Inspection | 32 sections; 100,000 traversed values; 100,000 explanation records; depth 64; 256 MiB canonical |
| Diff | 10,000 default records; 100,000 hard caller maximum; depth 64; 1,000,000 compared items; 256 MiB canonical |
| Domain Packs | 1,000 packs/registry; 10,000 assets/pack; 16 MiB canonical pack |
| Oracle Assertions | 1,000 assertions; path depth 64; 100,000 scan records; 1 MiB canonical |
| CLI | 16 MiB main input; 1 MiB auxiliary JSON; 256 MiB rendered output; 4,096 diagnostic characters |

## Security and unsupported behavior

Composition has one explicit local root, rejects traversal and symlink escape,
and reads bounded local files only. There are no network imports, dynamic Python
imports from YAML, automatic plugin/Domain Pack discovery, global registries, or
ambient environment semantics. DSE does not provide arbitrary Python execution
from YAML, hidden randomness, wall-clock semantic dependence, hidden network
calls, dynamic YAML imports, recursive subflows, unbounded loops, DB-backed
`ScenarioState`, ORM-owned state, raw SQL DSL, automatic Schemathesis HTTP
execution, indefinite incompatible cross-major replay, or implicit environmental
state. Explicit Python plugins and Python-packaged packs are trusted and
unsandboxed. See [security and non-goals](security-and-non-goals.md).
