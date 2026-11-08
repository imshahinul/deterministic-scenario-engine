# Deterministic Scenario Engine 3.2.0 candidate

The source distribution coordinate is 3.2.0. These prospective notes describe a
candidate and do not claim successful PyPI publication, a GitHub Release, or
merge. Engine 1 remains 1.0.0 and Engine 2 remains 2.0.0.

## Additive restricted minimizers

- `scenario_engine.engine2_shrink` adds `Engine2ShrinkRequest`,
  `Engine2ShrinkOutcome`, and `shrink_failed_scenario`. Its sole reduction
  operator deletes one whole actor declaration. Initially eligible actors were
  not selected before the original failure; the failing actor and target step
  are retained.
- `scenario_engine.engine2_input_shrink` adds `Engine2InputShrinkRequest`,
  `Engine2InputShrinkOutcome`, and `shrink_failed_inputs`. Its sole reduction
  operator deletes one element from one eligible input list per candidate. Only
  exact declared `$input` paths and descendants are eligible; unrelated sibling
  lists are excluded.

Use module-qualified imports:

```python
from scenario_engine.engine2_shrink import Engine2ShrinkRequest, shrink_failed_scenario
from scenario_engine.engine2_input_shrink import Engine2InputShrinkRequest, shrink_failed_inputs
```

There are no new package-root exports or CLI commands. Plugins are excluded.
Both APIs require one unchanged target source invariant, native `FAILED` /
`InvariantViolation` Result/2 and Schedule/1 evidence, fixed execution
coordinates, repeated deterministic runs, candidate-specific native evidence,
and exact replay of every accepted reduction. The preservation level is
`SOURCE_ANCHORED_SINGLE_INVARIANT_SIGNATURE`; it is restricted and is not
independent proof of general semantic equivalence.

Search is bounded by candidate and actual-execution budgets plus a cooperative
deadline. A deadline cannot terminate blocked code. Outcomes are noncanonical
summaries whose native children remain authoritative. A minimality statement is
made only after a complete pass over remaining eligible one-deletion candidates.
It is not a global optimality guarantee.

## Compatibility and non-goals

Result/2, Manifest/2, Schedule/1, Scheduler/1, and all native schemas are
unchanged. Existing suite and finite exploration behavior and golden identities
remain compatible. Engine 1 and Engine 2 execution behavior is unchanged.

The minimizers do not shrink individual steps, transitions, schedule choices,
schedule seeds, scalar values, mapping keys, or invariant expressions. They do
not provide broader step or schedule shrinking, general-purpose minimization,
semantic-equivalence proof, hard process isolation, or a global minimum. Repeated
local execution can have cost and side-effect implications, input content may be
sensitive, and trusted plugins generally remain unsandboxed even though plugin
execution is excluded here. See `docs/security-and-non-goals.md` and the two
minimizer guides for the complete boundary.

Controlled qualification demonstrated narrow synthetic fixture reduction and
candidate-native replay only. It does not establish real-world productivity or
user-demand evidence.
