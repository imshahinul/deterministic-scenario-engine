# DSL 2 logical-actor reference

**Status: PREPUBLICATION — DSE distribution 3.0.0 candidate.**

DSL 2 is selected only by integer `dsl_version: 2` and executes with Engine
2.0.0. It preserves DSL 1 expression, deterministic value, resource, plugin,
clock, and atomic-step foundations while declaring ordered logical actors. Each
actor has a canonical `scenario:/actor/<id>` address and an ordered `steps`
sequence. Unknown keys, duplicate identifiers, noncanonical addresses, invalid
types, and exceeded bounds fail before execution.

## Execution and evidence

Execution requires two independent coordinates:

- `root_seed` controls addressed generation;
- `schedule_seed` is an explicit unsigned 64-bit integer controlling scheduler
  selection and is never inferred from the root seed.

The public workflow is `scenario_engine.engine2.validate_engine2()`,
`execute_engine2()`, and `replay_engine2()`. It produces canonical
`scenario.result/2`, embedded `scenario.manifest/2`, and replay-authoritative
`scenario.schedule/1`. Exact replay rejects missing, altered, mixed-major, or
incompletely linked evidence.

## Analysis and limits

Result/2 supports actor-aware inspect/explain, conservative analysis, and the
offline static trace viewer. Inclusive resource ceilings cover actors, steps,
scheduler selections, canonical schedule bytes (8 MiB), canonical result bytes
(32 MiB), nesting depth, and input bytes. Duplicate JSON keys, remote URIs,
filesystem link traversal, noncanonical semantic addresses, invalid seeds, and
secret reflection are rejected or redacted.

## Unsupported capabilities

DSL 1/Engine 2 and DSL 2/Engine 1 execution are unsupported. There is no silent
migration, package-version inference, schedule-seed derivation, wall-clock or
network discovery, or Engine 2 suite orchestration. `suite.run/2` is a strict
schema/reader contract only.
