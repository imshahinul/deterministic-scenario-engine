# Engine 2 bounded actor-deletion minimizer

`scenario_engine.engine2_shrink` is an accepted restricted, module-qualified
API. Import `Engine2ShrinkRequest`, `Engine2ShrinkOutcome`, and
`shrink_failed_scenario` from that module only. It is not exported from the
package root, has no CLI, executes no plugins, and introduces no native artifact
contract.

## Scope

The only reduction operator deletes one complete DSL 2 actor declaration. The
initially eligible set contains original actors that were never selected in the
authoritative baseline Schedule/1, excluding the failing actor. Eligibility is
frozen before search. Actors are considered in canonical actor-address UTF-8
byte order by an ordered greedy search; acceptance restarts that order.

The source transformer accepts only separately lined block-style actor
mappings. It first uses the existing strict DSL parser/compiler, including
duplicate-key, alias, schema, transition, and declaration-limit checks. It then
uses YAML node source marks only to splice a whole actor line range. It does not
construct scenario values with a general YAML loader. Every candidate is parsed
and compiled again, and canonical non-actor content plus every retained actor
definition is compared with the baseline. Retained declaration text and order
are therefore not rewritten.

## Failure target

An eligible baseline has authoritative, linked Result/2 and Schedule/1 native
evidence whose classification is `FAILED` and code is exactly
`InvariantViolation`. Exact replay and at least three fixed-coordinate reruns
must reproduce the accepted canonical native bytes. The scenario must declare
exactly one post-state invariant, and the failing actor must contain exactly one
direct step and no subflows. Reruns independently check the runtime exception's
invariant ID and step ID against that source declaration.

Candidate acceptance requires the same observable native failure signature:
classification, code, actor address, and selection ordinal. It also requires
candidate-specific linked native evidence, repeated byte-identical executions,
and exact replay against the candidate's own schedule. The original schedule is
never replayed against changed source.

The accurate preservation label is
`SOURCE_ANCHORED_SINGLE_INVARIANT_SIGNATURE`. This is not a general semantic
oracle or a cross-scenario equivalence claim.

## Bounds and outcomes

`Engine2ShrinkRequest` fixes source, native evidence, root seed, schedule seed,
run index, effective inputs, candidate-evaluation budget, repetition count,
total execution budget, and an absolute monotonic-clock deadline. Candidate evaluations
are limited to 1 through 64. Repetition defaults to three and may not be below
three; its maximum is 16. Actor requests have no default for either the
candidate-evaluation budget or total execution budget. The total execution
budget is 1 through 1024 and includes baseline replay, baseline reruns, candidate
reruns, and candidate replay. Source is bounded to 1,048,576 UTF-8 bytes and
canonical inputs to 262,144 bytes.

Deadline checks occur between executions. They are not a hard timeout and do
not terminate blocked application code.

`Engine2ShrinkOutcome` is an immutable, noncanonical Python summary. Mapping
fields are read-only, and the source invariant-expression summary is
defensively copied into recursively read-only mappings and tuples; it does not
retain mutable dictionaries or lists from the compiled scenario. This summary
freezing neither changes invariant semantics nor defines a new evidence format.
Its final Result/2 and Schedule/1 children remain the authoritative evidence. A
completed final pass reports `1_MINIMAL_UNDER_ELIGIBLE_ACTOR_DELETION`, meaning
only that no remaining actor in the frozen eligible set passed one-at-a-time
deletion. Early budget/deadline termination reports
`MINIMALITY_NOT_ESTABLISHED`. Global minimality is never claimed. If no
candidate is accepted, the original source and native evidence are returned as
`NO_REDUCTION`.

## Security and non-goals

The reducer performs no network, shell, automatic plugin loading, scheduler
override, or unbounded enumeration. Input trees are validated, bounded, and
defensively copied; diagnostic summaries retain an input hash rather than raw
inputs. Scenarios declaring plugin generators are rejected without execution.
Trusted plugins remain unsandboxed and are excluded.

The reducer does not shrink steps, transitions, initial state, inputs, schedule
seeds, scheduler decisions, traces, invariant expressions, or plugins. It does
not repair invalid scenarios and does not modify Engine 1, Engine 2, scheduler,
canonical evidence, suite, release, or publication behavior.

## Tested synthetic installed-consumer example

This safe example has no plugins or untrusted callbacks. It constructs real
native baseline evidence at fixed coordinates, uses a bounded absolute monotonic
deadline, removes one never-selected actor, and exactly replays both original
and candidate-native evidence. Run it only with a distribution that provides
this 3.2.0 API.

<!-- installed-consumer-example:start -->
```python
from time import monotonic

from scenario_engine.engine2 import (
    construct_result2, execute_engine2, replay_engine2, validate_engine2,
)
from scenario_engine.engine2_shrink import (
    Engine2ShrinkRequest, shrink_failed_scenario,
)
from scenario_engine.invariants import InvariantViolation

source = """dsl_version: 2
scenario: actor-minimum
clock: {start: '2026-01-01T00:00:00Z'}
initial_state: {value: 0}
actors:
  - id: target
    steps:
      - id: fail
        write: {value: {$literal: 1}}
        transition: null
  - id: noise-a
    steps:
      - id: idle
        write: {value: {$state: value}}
        transition: null
invariants:
  - id: stays-zero
    check: {$lte: [{$state: value}, {$literal: 0}]}
"""
root_seed, schedule_seed, run_index = "example-root", 0, 2
scenario = validate_engine2(source)
try:
    execute_engine2(scenario, root_seed, schedule_seed, run_index=run_index)
except InvariantViolation as error:
    baseline_result = construct_result2(scenario, error.internal_outcome)
    baseline_schedule = error.internal_outcome.schedule
else:
    raise AssertionError("expected native FAILED evidence")

replay_engine2(baseline_result, baseline_schedule, scenario)
outcome = shrink_failed_scenario(Engine2ShrinkRequest(
    source=source, result=baseline_result, schedule=baseline_schedule,
    root_seed=root_seed, schedule_seed=schedule_seed, run_index=run_index,
    inputs=None, max_candidate_evaluations=8, total_execution_budget=64,
    deadline=monotonic() + 30, repetition_count=3,
))
assert outcome.status == "REDUCED"
assert outcome.removed_actor_addresses == ("scenario:/actor/noise-a",)
assert outcome.final_result is not None and outcome.final_schedule is not None
assert outcome.final_result.failure == baseline_result.failure
replay_engine2(
    outcome.final_result, outcome.final_schedule,
    validate_engine2(outcome.reduced_source),
)
```
<!-- installed-consumer-example:end -->

Controlled synthetic qualification found narrow diagnostic value: the reducer
can remove fixture noise while preserving this restricted native identity and
replay. That is synthetic-only evidence. It is not evidence of real-world
productivity, user demand, broad defect localization, or semantic equivalence.
