# Engine 2 bounded input-list minimizer

`scenario_engine.engine2_input_shrink` is an accepted restricted,
module-qualified API. Import `Engine2InputShrinkRequest`,
`Engine2InputShrinkOutcome`, and `shrink_failed_inputs` from that module only.
It is not exported from the package root, has no CLI, executes no plugins, and
defines no native artifact contract.

## Exact scope

The sole operator deletes one element from an eligible list in the explicit
Engine 2 input tree. It never rewrites DSL source, keys, scalars, actors, steps,
schedule records, seeds, or run indexes. Retained list elements preserve their
relative order. Candidate trees are independent copies and caller-owned trees
are never mutated.

Eligibility is frozen before search. By default, list paths are discovered only
at or below the exact dot-separated input paths named by DSL 2 resource `$input`
declarations. A declaration of a complete input root therefore includes its
descendant lists, while a nested declaration does not include unrelated sibling
lists under the same root. Multiple and overlapping declarations are unioned
without duplicate paths. A caller may provide a narrower explicit path set;
missing, non-list, or unconsumed paths are rejected. Paths use string mapping
segments and integer list segments and are ordered canonically by typed UTF-8 components. Lists are
visited in canonical path order and positions in ascending order. An accepted
deletion restarts ordered greedy search. If an earlier deletion invalidates a
frozen nested path, that path is safely skipped and recorded without changing
unrelated data.

The strict size metric is the UTF-8 byte length of the complete tree encoded by
the existing `scenario_engine.values.canonical_bytes` behavior. Acceptance
requires a strict decrease and an exact one-list-element transformation.

## Baseline and failure preservation

`Engine2InputShrinkRequest` supplies unchanged DSL 2 source, authoritative
Result/2 and Schedule/1, root seed, schedule seed, run index, original effective
inputs, optional eligible paths, candidate-evaluation limit, total actual
execution budget, repetition count, and cooperative monotonic deadline.

An eligible baseline has exactly one declared invariant, native `FAILED` /
`InvariantViolation` evidence, linked resource and execution coordinates, an
unambiguous declared failing actor, exact replay, and at least three identical
fixed-coordinate reruns. Runtime reruns anchor invariant ID and failed step ID
to the unchanged source. Scenarios declaring plugin generators are rejected and
no plugin registry or callback is accepted.

For every candidate, resources resolve before execution. At least three runs
must produce byte-identical candidate-native Result/2 and Schedule/1 evidence.
The classification, failure code, actor, selection ordinal, runtime invariant
ID, and failed step ID must match the original. Result/schedule linkage and the
candidate resource hashes are checked, then the candidate's own schedule is
exactly replayed against the candidate inputs. The original schedule is never
replayed against changed resources, and candidate resource hashes are not
required to equal original hashes.

The preservation label is
`SOURCE_ANCHORED_SINGLE_INVARIANT_SIGNATURE`. Matching this restricted
signature is not independent proof of full semantic equivalence.

## Bounds, outcomes, and minimality

Candidate evaluations default to 64 and are bounded to 1..64. Actual engine
executions default to 128, are bounded to 1..128, and include baseline replay, baseline reruns,
candidate runs, and candidate replay. The budget is checked before each actual
execution. Repetition defaults to three and is bounded to 3..16. The constructor
deadline default is `0.0`, so practical calls must supply a future absolute
monotonic deadline. Input size is at most 262,144 canonical bytes, nesting depth
is at most 32, and source is at most 1,048,576 UTF-8 bytes. Booleans are rejected for integer budget
fields. Cycles, mutable aliases, ambiguous container types, unsupported values,
and oversized trees fail closed.

The deadline is checked cooperatively between executions; it is not a hard kill
for blocked or untrusted code. Untrusted code and plugins are outside scope.

`Engine2InputShrinkOutcome` is an immutable, noncanonical Python summary. Its
public constructor defensively snapshots recursively mutable summary fields and
validates snapshot sizes; it contains frozen original/reduced snapshots, canonical sizes,
deletion coordinates, fixed execution coordinates, native identities and final
native children, counts, bounded redacted rejection reasons, replay and
determinism status, stop reason, and limitations. Input fields are excluded from
default representations and are never automatically serialized or logged. The
summary is not tamper-proof evidence; its Result/2 and Schedule/1 children are
the authoritative native evidence under their own existing contracts.

`1_MINIMAL_UNDER_ELIGIBLE_LIST_DELETIONS` is reported only after a complete
final pass over every remaining eligible one-element deletion. It is a
conditional one-deletion statement, never a global minimum. Deadline or budget
stops report `MINIMALITY_NOT_ESTABLISHED`. If no candidate is accepted, the
truthful status is `NO_REDUCTION`.

## Non-goals

This API does not delete mapping keys, shrink scalars, reorder collections,
alter DSL source, edit schedules, explore seeds, execute plugins, invoke the
network or shell, serialize audits, or change Engine 1/2, Result/2, Manifest/2,
Schedule/1, suite, exploration, release, or publication behavior.

## Tested synthetic installed-consumer example

This safe fixture makes `[2, 1]` fail because its length is nonzero. Deleting
`2` preserves the restricted failure as `[1]`; deleting the final element would
produce success and is rejected. The example uses fixed coordinates, real native
baseline evidence, a bounded monotonic deadline, and exact original/candidate
replay without plugins or untrusted callbacks.

<!-- installed-consumer-example:start -->
```python
from time import monotonic

from scenario_engine.engine2 import (
    construct_result2, execute_engine2, replay_engine2, validate_engine2,
)
from scenario_engine.engine2_input_shrink import (
    Engine2InputShrinkRequest, shrink_failed_inputs,
)
from scenario_engine.invariants import InvariantViolation

source = """dsl_version: 2
scenario: input-minimum
clock: {start: '2026-01-01T00:00:00Z'}
initial_state: {value: 0}
resources:
  cfg: {$input: cfg}
actors:
  - id: target
    steps:
      - id: fail
        write: {value: {$len: {$resource: cfg}}}
        transition: null
invariants:
  - id: stays-zero
    check: {$lte: [{$state: value}, {$literal: 0}]}
"""
inputs = {"cfg": [2, 1]}
root_seed, schedule_seed, run_index = "example-root", 0, 2
scenario = validate_engine2(source)
try:
    execute_engine2(
        scenario, root_seed, schedule_seed, run_index=run_index, inputs=inputs,
    )
except InvariantViolation as error:
    baseline_result = construct_result2(scenario, error.internal_outcome)
    baseline_schedule = error.internal_outcome.schedule
else:
    raise AssertionError("expected native FAILED evidence")

replay_engine2(baseline_result, baseline_schedule, scenario, inputs=inputs)
outcome = shrink_failed_inputs(Engine2InputShrinkRequest(
    source=source, result=baseline_result, schedule=baseline_schedule,
    root_seed=root_seed, schedule_seed=schedule_seed, run_index=run_index,
    inputs=inputs, max_candidate_evaluations=8, total_execution_budget=64,
    repetition_count=3, deadline=monotonic() + 30,
))
reduced_inputs = {"cfg": list(outcome.reduced_inputs["cfg"])}
assert outcome.status == "REDUCED" and reduced_inputs == {"cfg": [1]}
assert outcome.accepted_count == 1 and outcome.rejected_count == 1
assert outcome.final_result is not None and outcome.final_schedule is not None
assert outcome.final_result.failure == baseline_result.failure
replay_engine2(
    outcome.final_result, outcome.final_schedule, scenario, inputs=reduced_inputs,
)
```
<!-- installed-consumer-example:end -->

Controlled synthetic qualification found narrow diagnostic value for this
causally relevant list fixture and for excluding unrelated sibling lists. These
are synthetic-only findings, not evidence of real-world productivity, user
demand, broad input simplification, or general semantic equivalence.
