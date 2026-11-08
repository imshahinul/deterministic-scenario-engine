# Engine 2 bounded input-list minimizer

`scenario_engine.engine2_input_shrink` is a module-qualified, local-candidate
API. It is not exported from the package root, has no CLI, and defines no native
artifact contract.

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

Candidate evaluations are bounded to 1..64. Actual engine executions are
separately bounded to at most 128 and include baseline replay, baseline reruns,
candidate runs, and candidate replay. The budget is checked before each actual
execution. Repetition is at least three. Input size and nesting use established
Engine 2 suite compatibility bounds. Booleans are rejected for integer budget
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
