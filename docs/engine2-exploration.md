# Engine 2 deterministic schedule-seed exploration

## Scope and module-qualified API

`scenario_engine.engine2_explore` provides:

* `Engine2SeedSweepRequest`;
* `Engine2SeedSweepOutcome`; and
* `explore_engine2_seeds(request)`.

These names are deliberately not package-root exports. A sweep is a finite,
serial convenience operation over the existing hardened Engine 2 suite runner.
It is not systematic scheduler branching, exhaustive model checking, state-space
coverage, race-detection completeness, minimization, shrinking, distributed
execution, or actual parallel execution.

## Request and deterministic coordinates

`Engine2SeedSweepRequest` requires one validated `CompiledScenarioV2`, one
explicit root seed, an explicit run index, and an exact `list` or `tuple` of
schedule seeds. It optionally accepts one supplied-input mapping and one explicit
trusted `PluginRegistry`. The common expectation is `SUCCESS`, or `FAILED` plus
one common expected failure code.

The seed collection must contain 1..64 unique integers in `0..2^64-1`.
Booleans, strings, floats, duplicates, sets, mappings, generators, empty
collections, and larger collections fail before execution. No seed is derived or
randomly generated, and supplied order is preserved exactly.

Each seed becomes one `Engine2CaseRequest`; that accepted type remains the
validator for scenario, root seed, run index, resources, inputs, plugins,
compatibility coordinates, and expectations. Case identifiers use the fixed
zero-based format `seed-sweep-{position:02d}` (for example, `seed-sweep-00`).
Position and schedule seed are identity-bearing, so seed reordering changes the
plan identity. Across cases only schedule seed, position, case ID, and resulting
case identity vary. Scenario, scenario identity, root seed, run index, inputs,
effective resources, plugin registry identity, expectation, and native
compatibility coordinates remain fixed. Each native execution receives a fresh
thawed input value; mutable execution state is not shared between cases.

## Outcome and authoritative evidence

`explore_engine2_seeds` constructs one `Engine2SuitePlan` and calls the existing
`execute_engine2_suite` once. Execution is serial and plan ordered. The immutable
`Engine2SeedSweepOutcome` exposes its original `Engine2SuiteOutcome` as `suite`.
The seed list, IDs, identities, plan identity, attempted count, four status
counts, non-success case coordinates, and first-observed distinct native schedule
artifact identities are derived only from that suite outcome. They are not a
second canonical evidence contract or competing source of truth.

Direct construction of `Engine2SeedSweepOutcome` validates, without executing or
replaying the suite, that its authoritative suite has the seed-sweep shape. Case
IDs and positions must exactly match their ordered `seed-sweep-{position:02d}`
coordinates, schedule seeds must be unique native-range integers, and every
other request coordinate must be identical across cases. Consequently an
ordinary suite, or a suite heterogeneous in scenario, root seed, run index,
inputs, resources, plugins, expectations, or native compatibility coordinates,
cannot be silently presented as a seed sweep.

Every `SUCCESS`, `EXPECTED_FAILURE`, `UNEXPECTED_FAILURE`, and `ERROR` remains in
the suite. Expected failure changes only the suite-level status interpretation;
the native Result/2 and Schedule/1 remain `FAILED`. Completed cases retain exact
Result/2, Manifest/2, and Schedule/1 authority. An `ERROR` has no fabricated
native children and cannot independently provide replayable native evidence. A
runtime suite retention or selection limit remains a truthful `ERROR` according
to the existing fail-closed suite contract.

The `schedule_artifact_identities` field is useful for exact artifact comparison,
but distinct hashes do **not** prove distinct logical interleavings: schedule
artifact identity includes execution coordinates such as the schedule seed. No
new scheduling-decision trace equivalence is inferred.

## Offline verification and exact replay

Canonical suite bytes continue to use `read_engine2_suite`, followed by
`verify_engine2_suite(suite, child_evidence)` for aggregate integrity, exact
native child bytes, native identities, and coordinate linkage. Aggregate
verification is not replay and no second verifier is introduced.

Each completed in-memory case can be replayed separately:

```python
from scenario_engine.engine2 import replay_engine2

for case in outcome.suite.cases:
    if case.result is not None and case.schedule is not None:
        replay_engine2(
            case.result,
            case.schedule,
            scenario,
            inputs=original_inputs,
            plugins=trusted_plugins,
        )
```

Replay requires the exact scenario and may require the original effective
supplied inputs. Plugin cases require the exact trusted registry. Plugins are
unsandboxed Python, are not discovered, and are not a security boundary. Error
records without native children are not independently replayable evidence.

## Resource limits

The operation inherits all accepted suite limits: at most 64 cases; 262,144
canonical input bytes per case; 4,194,304 aggregate input bytes; 524,288 request
bytes per case; 1,048,576 aggregate request bytes; nesting depth 32; 65,536
native selections per case; 262,144 aggregate selections; 67,108,864 retained
child bytes; and 2,097,152 canonical suite bytes. Seed validation is finite and
occurs before execution. Plan validation does not invoke plugin callables.

## Minimal consumer example

```python
from scenario_engine.engine2 import validate_engine2
from scenario_engine.engine2_explore import Engine2SeedSweepRequest, explore_engine2_seeds

scenario = validate_engine2(open("scenario.yaml", encoding="utf-8").read())
outcome = explore_engine2_seeds(Engine2SeedSweepRequest(
    scenario=scenario,
    root_seed="release-17",
    schedule_seeds=[0, 1, 9],
    run_index=0,
))
print(outcome.plan_identity, outcome.suite.aggregate_hash, outcome.success_count)
```

The tested contract suite validates the same API workflow with inline supported
DSL 2 scenarios; this file-dependent consumer snippet is illustrative and does
not claim validation of an external `scenario.yaml`.
