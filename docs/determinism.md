# Determinism model

## ExecutionAddress

Every generated value is associated with an `ExecutionAddress`. Its semantic
components are:

- scenario ID;
- run index;
- nested subflow invocation path;
- repetition indexes;
- executable step ID; and
- semantic field path.

Adding an unrelated generator gives it a different address; it does not consume
from and shift a shared stream. Renaming or moving addressed semantic elements
can intentionally change their generated values.

## Addressed RNG and IDs

The addressed RNG derives generation from the root seed plus the explicit
semantic address. `LogicalID` generation is addressed in the same way, so IDs
are stable when their address and execution context are stable. The public
contract versions both algorithms in `ReproducibilityManifest`; internal hash
mechanics are not part of this conceptual guarantee.

## Logical clock

Each scenario declares an aware reference-clock start. Successful executable
steps advance that logical clock by their declared nonnegative duration. The
engine does not read wall-clock time to execute a scenario. Failed steps do not
advance the clock.

## Whole-step atomicity

An executable step follows this conceptual sequence:

```text
PRE-STATE
→ generate locals
→ derive prospective values
→ construct patch
→ candidate POST-state
→ validate candidate/invariants
→ candidate emissions
→ resolve transition
→ ATOMIC COMMIT
```

Expressions for `$state` read pre-state while emission `$state` fields read the
candidate post-state. If derivation, invariant evaluation, emission construction,
or transition resolution fails, there is no partial observable mutation: no
state patch, clock advance, history record, or artifact from that step commits.

## State, history, and ground truth

`ScenarioState` is the current logical state used by the execution kernel.
`ScenarioHistory` is the append-only sequence of committed step records. Users
normally observe both through `ScenarioResult`: `final_state` reads current
state, `history` exposes committed history, `trace()` returns normalized history,
and `artifacts` exposes committed artifacts. Together they provide test ground
truth rather than only generated values.

## Ordering

Order is semantic for root steps, subflow steps, branch cases, repeat iterations,
emission declarations, validator/constraint/invariant/fault declarations, history,
and artifacts. Branches select the first true case. Mappings used as semantic
records are canonicalized by key for deterministic hashing/serialization, and
declarative derivations are dependency-resolved rather than source-key ordered.
Canonical JSON uses sorted mapping keys. Do not use mapping insertion order to
encode business sequencing; use an ordered DSL list.

See [reproducibility](reproducibility.md) for recorded context and
[compatibility](compatibility.md) for the normative replay contract.
