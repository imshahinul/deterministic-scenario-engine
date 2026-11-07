# Engine 2 bounded actor-deletion minimizer

`scenario_engine.engine2_shrink` is a module-qualified local-candidate API. It
is not exported from the package root, has no CLI, and introduces no native
artifact contract.

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
three. The total execution budget includes baseline replay, baseline reruns,
candidate reruns, and candidate replay.

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
