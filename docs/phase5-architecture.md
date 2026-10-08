# Phase 5.0 Step-Atomic Deterministic Logical Concurrency Architecture Freeze

## 1. Status and authority

This document freezes the approved Phase 5 product direction: **Step-Atomic
Deterministic Logical Concurrency**. It is a design and scope checkpoint, not an
implementation or release authorization. Phase 4 is complete; Phase 5
implementation has not started.

The immutable entry baseline is distribution and release tag `2.2.0`, commit
`aaa0495239df9db093c5e42d817a9d449e5ea055`, tree
`c61e7380e848b789388d351470bb0d99d06db0b7`.

```text
PHASE5_SCOPE_FROZEN=YES
PHASE5_IMPLEMENTATION_STARTED=NO
PHASE5_1_AUTHORIZED=NO
PHASE5_PRODUCTION_CODE_CHANGED=NO
PHASE5_VERSION_VALUES_CHANGED=NO
```

The future targets below are not current values and are not authorized release
metadata changes:

| Version role | Frozen future target | Meaning |
|---|---:|---|
| Distribution | `3.0.0` | Packaging and publication identity only |
| Engine | `2.0.0` | Deterministic execution and replay compatibility major |
| Manifest engine | `2.0.0` | `engine_version` recorded by an Engine 2 manifest |
| DSL | integer `2` | Syntax/semantic dispatch selector for logical actors |
| Result | `scenario.result/2` | Actor- and schedule-aware result contract |
| Suite run | `suite.run/2` | Engine 2 run/replay envelope contract |

Distribution, engine, manifest schema, manifest engine value, DSL, result,
suite, scheduler, and schedule-evidence versions are independent roles. No role
is inferred from another.

## 2. Product boundary

Phase 5 adds:

- uniquely named logical actors (also called lanes in presentation only);
- one shared scenario state and one shared logical clock;
- deterministic interleaving between atomic actor transitions;
- a separately versioned deterministic scheduler and independent schedule seed;
- a canonical schedule identity and exact schedule replay;
- actor-aware immutable history, diagnostics, and static trace viewing; and
- explicit DSL 1/Engine 1 and DSL 2/Engine 2 dispatch boundaries.

Actors are logical engine entities. They are not operating-system threads,
processes, tasks, coroutines, or `asyncio` objects. Execution may be implemented
serially and its meaning cannot depend on host scheduling.

Phase 5 explicitly excludes schedule exploration, partial-order reduction,
schedule shrinking, microstep or yield scheduling, locks, semaphores, real
threading, `asyncio` semantics, distributed workers, hosted UI, an adapter
marketplace, runtime LLM integration, network execution authority, and any
general workflow service.

## 3. Preserved contracts and compatibility boundary

The following Phase 4 contracts remain unchanged and independently versioned:

```text
scenario.semantic-address/1
scenario.error/1
scenario.scaffold/1
scenario.definition-diff/1
scenario.impact/1
scenario.trace-view/1
scenario.compatibility-fixtures/1
suite.run/1
```

The frozen DSL 1 parser, Engine 1.0.0 execution semantics, whole-step atomicity,
`scenario.result/1`, `scenario.manifest/1`, `suite.run/1`, deterministic RNG and
ID behavior, golden result bytes, existing supported replay behavior, root APIs,
CLI behavior, and immutable historical artifacts are not modified in place.

Phase 5 requires new contracts because actor and schedule coordinates cannot be
added to the frozen normalized fields of `scenario.result/1` or
`scenario.manifest/1`, and cannot be added to `suite.run/1` without changing its
accepted meaning. Engine 2 therefore uses the new `scenario.result/2`,
`scenario.manifest/2`, and `suite.run/2` contracts. The manifest schema name is
an architectural consequence of the frozen v1 field set; it is independent of
the manifest's future `engine_version == "2.0.0"` value.

Historical bytes are read under their declared contract. Readers never infer a
new contract from package version, add missing actor/schedule fields, or silently
upgrade an artifact. Unknown, mixed, incomplete, or unsupported version tuples
fail closed. Inspection, diff, migration, execution, and replay remain separate
capabilities.

## 4. Actor model and identity

An actor declaration has a nonempty unique author-assigned identifier. Actor
identity is the canonical `scenario.semantic-address/1` address
`scenario:/actor/<identifier>` using the existing normalization, escaping,
depth, length, equality, and ordering rules. A step in an actor is addressed as
`scenario:/actor/<identifier>/step/<step-id>`. No raw YAML path, list index,
source order, host thread identifier, or display label is durable actor identity.

The Phase 4 reserved `actor` kind is activated without changing the grammar or
meaning of existing semantic addresses. `lane` remains presentation terminology
and is not a second identity namespace. Actor ordering is unsigned
lexicographic ordering of canonical semantic-address UTF-8 bytes. Declaration
order may be retained for author presentation but has no scheduler authority.

All actors observe and atomically update one shared `ScenarioState`. There is no
actor-owned copy, merge phase, shared mutable resource cache, or DB/ORM-owned
state. Generated locals and derived values are invocation-local and disappear at
the transition boundary. An actor's next-node/program-counter position is
deterministic scheduler control state, not user scenario state. New persistent
actor-private mutable state is not implicit: authors represent it explicitly in
the shared state if needed.

## 5. Atomic execution semantics

The scheduling boundary is one existing whole executable step. For a selected
actor, deterministic control routing needed to locate its next executable step
is resolved without yielding and without mutating shared state. A scheduler
cannot interleave inside generation, derivation, patch construction, validation,
invariant evaluation, emission construction, transition resolution, or commit.

```text
select ready actor
→ resolve actor's next executable step
→ snapshot shared PRE-state and shared logical clock
→ apply matching before-step faults
→ generate actor-step locals
→ derive prospective values
→ construct shared-state patch
→ candidate shared POST-state
→ validate candidate and evaluate invariants
→ construct candidate emissions
→ resolve actor transition
→ ATOMIC COMMIT of state, clock, history, artifacts, and actor position
```

Existing before-validation resource faults, resource validation, and constraints
remain pre-execution setup and complete before scheduling starts. Within a
selected transition, matching faults retain declaration order. Candidate
validation and invariants precede emissions and transition resolution, as in the
frozen whole-step model. A derivation, fault, validation, invariant, emission, or
transition failure commits no state patch, clock advance, history record,
artifact, or actor-position advance.

There is exactly one shared logical clock. Each successfully committed selected
step advances it by that step's declared nonnegative duration. A failed step does
not advance it. Simultaneous wall-clock time, time slicing, and host timing have
no semantic meaning.

## 6. Readiness, completion, and failure

At a scheduling point, an actor is:

- **ready** when deterministic control routing reaches a next executable step;
- **terminal** when its declared actor flow has completed; or
- **failed** when its selected transition raises a deterministic execution
  failure.

Control routing is finite and bounded and cannot itself be a scheduling yield.
There are no lock, semaphore, sleep, mailbox, external-event, or host-I/O waiting
states in Phase 5. If no actor is ready and every actor is terminal, the scenario
completes. If no actor is ready while any actor is nonterminal, execution fails
closed with a deterministic scheduler-stall error; it is never guessed to be
successful. The actor set is fixed before execution; actors cannot spawn actors.

Only the selected actor attempts a transition. A transition failure terminates
the scenario; no other actor runs afterward. The schedule trace records that
selection as an attempted selection with its outcome, while committed scenario
history contains only successful atomic commits. Thus diagnostics can identify
the failing actor without weakening immutable committed-history semantics.

## 7. Scheduler and schedule seed

### 7.1 Normative `scenario.scheduler/1` contract

The scheduler is a pure logical selector. Its exact normalized coordinate
envelope is:

```json
{"contract":"scenario.scheduler/1","coordinates":{"committed_history_length":0,"input_resource_hashes":{},"logical_clock":{"$type":"datetime","value":"2026-01-01T00:00:00.000000+00:00"},"ready_actors":[],"run_index":0,"scenario_hash":"0000000000000000000000000000000000000000000000000000000000000000","schedule_seed":0,"selection_ordinal":0}}
```

The example's empty `ready_actors` illustrates the schema only and is not a
valid selector request. The fields and nesting are exact; no additional field,
omitted field, alias, or `null` value is accepted.

| Coordinate | Exact semantic type and encoding |
|---|---|
| `contract` | Exact string `scenario.scheduler/1`; this field is the sole domain separator |
| `scenario_hash` | Required canonical scenario-definition hash: exactly 64 lowercase hexadecimal ASCII characters |
| `input_resource_hashes` | Exact public manifest `input_resource_hashes` string-to-string mapping, with its existing `input:<name>` / `resource:<name>` and fingerprint semantics; normalized by the existing semantic normalizer, which sorts mapping keys |
| `run_index` | Required nonnegative Python integer excluding `bool`; any tighter inherited producer limit remains applicable |
| `schedule_seed` | Required independent Python integer excluding `bool`, inclusive range 0 through 18,446,744,073,709,551,615 (`2^64-1`) |
| `selection_ordinal` | Required zero-based Python integer excluding `bool`, inclusive range 0 through 65,535; at most 65,536 selections exist |
| `committed_history_length` | Required nonnegative Python integer excluding `bool`; number of committed transition records before this decision |
| `logical_clock` | Required timezone-aware `datetime` semantic value for the one shared logical clock; existing normalization converts it to UTC `{"$type":"datetime","value":"<ISO-8601 with exactly six fractional digits and +00:00>"}` |
| `ready_actors` | Nonempty unique subset of declared canonical actor addresses, normalized into unsigned lexicographic order of their UTF-8 bytes |

Declared and ready actors must be canonical `scenario.semantic-address/1`
strings of the exact activated actor shape `scenario:/actor/<identifier>`.
Every ready actor must be declared; declared actors and ready actors are each
unique. Actor declaration order and caller ready-set order have no authority.

The envelope is passed once through the existing canonical semantic normalizer
and JSON serializer: UTF-8, sorted object keys, compact separators,
`ensure_ascii=false`, no trailing newline, and no locale or whitespace
dependence. No byte prefix is prepended. SHA-256 hashes all and only those exact
bytes. The complete 32-byte digest is interpreted as an unsigned big-endian
256-bit integer. For normalized ready list `R`:

```text
selected_index = digest_integer modulo len(R)
selected_actor = R[selected_index]
```

An empty ready set is rejected before hashing or modulo; all-terminal completion
and nonterminal scheduler-stall classification belong to actor control
integration, not this pure selector. With one ready actor the complete canonical
bytes and SHA-256 digest are still computed and returned, and the selected index
is zero.

Validation fails closed without coercion, truncation, clamping, deduplication,
or partial output. Missing coordinates, booleans in integer fields, negative or
over-limit integers, floats, numeric strings, naive datetimes, malformed or
noncanonical hashes or actor addresses, duplicate actors, undeclared ready
actors, non-string resource names/hashes, and unsupported semantic values are
errors. Validation precedence is the coordinate table order, followed by
declared actors, then ready actors; within an actor sequence input order is used
only to identify the first invalid or duplicate value. Stable diagnostics expose
the failed public field or limit, never arbitrary value representations.

`schedule_seed` is independent from the existing generation `root_seed`.
Neither seed is derived from the other. Actor selection never consumes addressed
generator RNG state and generation never consumes scheduler state. Scheduler
choices depend only on the envelope. Process history, worker timing, filesystem
enumeration, environment, network, wall clock, runtime object identity, Python
hash randomization, and global mutable state are forbidden inputs.

The algorithm and every output-affecting representation above are immutable for
`scenario.scheduler/1`. A behavior change requires a new scheduler contract;
distribution or implementation versions cannot silently change it. This
contract does not construct readiness, execute actors, route control, classify
completion or stalls, mutate state or clock, persist or replay schedules, emit
`scenario.schedule/1` or `scenario.result/2`, explore schedules, or provide host
parallelism.

### 7.2 Independent golden vectors

These vectors were calculated by a standalone Python standard-library reference
using `json.dumps(..., ensure_ascii=False, separators=(",", ":"),
sort_keys=True)`, `hashlib.sha256`, `int(digest, 16)`, and modulo; it imports no
scheduler or Scenario Engine code. Each `bytes` value below is the exact UTF-8
text (with no trailing newline).

**V1 — one actor, seed 0, ordinal 0**

```text
bytes={"contract":"scenario.scheduler/1","coordinates":{"committed_history_length":0,"input_resource_hashes":{},"logical_clock":{"$type":"datetime","value":"2026-01-01T00:00:00.000000+00:00"},"ready_actors":["scenario:/actor/alpha"],"run_index":0,"scenario_hash":"0000000000000000000000000000000000000000000000000000000000000000","schedule_seed":0,"selection_ordinal":0}}
sha256=db753de068e327a09694ccd0b4676a0c602fe9c5380f7e185a0835a1b194bc66
selected_index=0
selected_actor=scenario:/actor/alpha
```

**V2 — two actors supplied in reverse order, seed 1, ordinal 0, manifest input identity**

```text
bytes={"contract":"scenario.scheduler/1","coordinates":{"committed_history_length":0,"input_resource_hashes":{"input:user":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},"logical_clock":{"$type":"datetime","value":"2026-01-01T00:00:00.000000+00:00"},"ready_actors":["scenario:/actor/alpha","scenario:/actor/beta"],"run_index":0,"scenario_hash":"0000000000000000000000000000000000000000000000000000000000000000","schedule_seed":1,"selection_ordinal":0}}
sha256=d14c771920e3d451645bfd62d9458225c667ae824ab838516ae5abab4b19585d
selected_index=1
selected_actor=scenario:/actor/beta
```

**V3 — three actors, Unicode identifier, seed 0, ordinal 1**

```text
bytes={"contract":"scenario.scheduler/1","coordinates":{"committed_history_length":1,"input_resource_hashes":{},"logical_clock":{"$type":"datetime","value":"2026-01-01T00:00:01.000002+00:00"},"ready_actors":["scenario:/actor/%C3%A9clair","scenario:/actor/alpha","scenario:/actor/beta"],"run_index":7,"scenario_hash":"ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff","schedule_seed":0,"selection_ordinal":1}}
sha256=3abc028519a8d1dd300fec26e33744182198e8f871cadbff138c75f699cca87b
selected_index=1
selected_actor=scenario:/actor/alpha
```

Supplying V3's ready actors as `beta`, `%C3%A9clair`, `alpha` produces the exact
same normalized bytes, digest, index, and actor. Together V1–V3 freeze one, two,
and three actors, two seeds, two ordinals, reordered input, manifest resource
identity, and a canonical NFC Unicode actor identifier.

## 8. Schedule identity and replay authority

The independently versioned schedule evidence contract is
`scenario.schedule/1`. The exact top-level wire object has these fields and no
others:

```json
{"actors":[],"contract":"scenario.schedule/1","execution":{"dsl_version":2,"engine_version":"2.0.0","generator_versions":{},"id_algorithm_version":"scenario.logical-id/1","locale":"C","reference_clock_start":{"$type":"datetime","value":"2026-01-01T00:00:00.000000+00:00"},"rng_algorithm_version":"scenario.rng/1","root_seed":0},"input_resource_hashes":{},"records":[],"run_index":0,"scenario_hash":"0000000000000000000000000000000000000000000000000000000000000000","schedule_hash":"0000000000000000000000000000000000000000000000000000000000000000","schedule_seed":0,"scheduler_contract":"scenario.scheduler/1","terminal":{"classification":"SUCCESS","failure":null}}
```

The shown algorithm-version strings are illustrative schema values; producers
must record the exact frozen constants used by execution. `contract` and
`scheduler_contract` are the exact strings shown. `scenario_hash` and
`schedule_hash` are exactly 64 lowercase hexadecimal ASCII characters.
`input_resource_hashes` is the exact canonical string-to-string mapping used by
the scheduler. `run_index` is a nonnegative integer excluding `bool` and
`schedule_seed` is an integer excluding `bool` in `0..2^64-1`. `actors` is the
nonempty, unique declared actor set in canonical-address UTF-8 byte order, with
at most 32 entries.

`execution` has exactly `dsl_version`, `engine_version`, `generator_versions`,
`id_algorithm_version`, `locale`, `reference_clock_start`,
`rng_algorithm_version`, and `root_seed`. DSL is exact integer `2`, engine is
exact string `2.0.0`, locale is exact string `C`, reference clock is a
timezone-aware datetime normalized to UTC, root seed is a string or integer
excluding `bool`, generator versions are a canonical string-to-string mapping,
and the RNG and ID versions are the exact nonempty constants used by the actor
kernel. These are schedule replay coordinates, not a public Manifest/2 and not a
change to the released Engine 1.0.0 value.

Each member of `records`, in list order, has exactly:

```json
{"committed_history_length":0,"logical_clock":{"$type":"datetime","value":"2026-01-01T00:00:00.000000+00:00"},"outcome":"COMMITTED","ready_actors":["scenario:/actor/alpha"],"scheduler_digest":"0000000000000000000000000000000000000000000000000000000000000000","selected_actor":"scenario:/actor/alpha","selection_ordinal":0}
```

`selection_ordinal` is the record's zero-based list position and is in
`0..65,535`. `ready_actors` is the nonempty unique ready subset in canonical
actor-address UTF-8 byte order. `selected_actor` is a member of that set.
`committed_history_length` is the nonnegative count immediately before the
decision, not an alias for ordinal. `logical_clock` is the shared clock
immediately before the decision. `scheduler_digest` is the exact lowercase
SHA-256 digest returned by `scenario.scheduler/1` for those coordinates.
`outcome` is exact `COMMITTED` or `FAILED`; every record except possibly the
last is `COMMITTED`. A record is created after selection and before transition
execution, so a failed attempted selection remains `FAILED` and creates no
committed history, clock advance, artifact, or actor-position advance.

`terminal` has exactly `classification` and `failure`. Successful completion is
exactly `{"classification":"SUCCESS","failure":null}` and includes empty
completed schedules when all validated actors are initially terminal. Failed
execution is exact classification `FAILED`; `failure` then has exactly
`actor`, `code`, and `selection_ordinal`, identifying the final failed record.
The code is the stable nonempty exception `code` when present, otherwise the
exception class name; no message, value, traceback, path, seed, preimage, or
secret-bearing detail is recorded. Scheduler stall and resource-limit failures
that occur before a selection record can be created are execution failures and
do not produce a completed schedule artifact.

The **schedule identity payload** is the complete top-level object with only
`schedule_hash` omitted; all other fields, including terminal/failure evidence,
are included. It is normalized once by DSE's existing semantic normalizer and
serialized as UTF-8 JSON with sorted object keys, compact separators,
`ensure_ascii=false`, and no trailing newline or prefix. `schedule_hash` is the
lowercase hexadecimal encoding of SHA-256 over exactly those bytes. The complete
artifact is the same canonical serialization after adding `schedule_hash`.
Both identity bytes and complete artifact bytes must be at most 8,388,608 bytes
before an artifact is accepted or returned. No partial or prefix artifact is a
schedule. Identical coordinates and decisions therefore produce byte-identical
artifacts and hashes; distinct seeds can legitimately produce the same actor
choices but remain distinct identity payloads because the seed is included.
A hash match alone proves neither execution validity nor successful replay.

Readers accept bytes or UTF-8 text only, reject an input over the byte ceiling
before JSON decoding, reject malformed UTF-8/JSON, non-finite numbers, duplicate
keys, nesting deeper than 32, missing or unknown fields, invalid exact types,
noncanonical actor addresses/order, unsupported contracts/versions, excessive
records, ordinal/order inconsistencies, invalid terminal shape, and a corrupted
hash. There is no unknown-field preservation, coercion, repair, migration,
network retrieval, path interpretation, or executable hook. Validation is
fail-closed and diagnostics name only the stable field, contract, or public
limit; supplied values and hash preimages are not reflected.

Exact internal Engine 2 replay requires the validated schedule, exact scenario,
explicit inputs/resources, and plugin registry needed by the scenario. Before
execution it verifies the contract/hash, scenario hash, resource hashes, run
index, seed, initial actor set, and every execution-version coordinate. It then
independently reconstructs routing/readiness and calls `scenario.scheduler/1` at
every selection. Before executing each transition it compares record position,
ordinal, ready set, selected actor, scheduler digest, committed-history length,
and logical clock. It never executes merely because an actor was named by the
record. Missing, extra, or reordered records fail closed at the first boundary
before an unverified transition commits.

Replay preflights record count against both
`MAX_SCHEDULER_SELECTIONS == 65,536` and
`MAX_REPLAY_SCHEDULER_SELECTIONS_VERIFIED == 65,536`, incrementally checks before
each verification, and applies the same 4,096 routing-operation ceiling.
Following execution it reconstructs a new schedule and compares canonical bytes,
terminal/failure classification, selection order, committed history, final
shared state, logical clock, actor terminal positions, and deterministic outcome
classification. Failure replay must reproduce the same final failed selection
and stable failure code without a partial commit. Source schedule objects are
immutable and are never repaired or mutated. Exact replay returns only internal
evidence; it does not publish Result/2, Manifest/2, or Suite Run/2.

A mismatch in scenario, inputs/resources, actor set, ready set, selected actor,
selection count, scheduler version, seed, or any other required coordinate fails
closed before the mismatched transition commits. Recorded actor selections are
evidence to verify, not authority to force an actor that is not ready. Missing
coordinates cannot be reconstructed from fingerprints. Migration or
inspectability never implies replayability.

## 9. Actor-aware history, result, and diagnostics

`scenario.result/2` is a new normalized envelope. It carries Engine 2 manifest
coordinates, final shared state and clock, actor terminal positions/statuses,
ordered committed history, artifacts, provenance when present, and complete
bounded schedule evidence/identity. Every history and provenance event that
arises in actor execution carries the canonical actor address. Actor-qualified
step addresses use `scenario.semantic-address/1`; Engine 1 `ExecutionAddress`
JSON is not reinterpreted as an actor address.

History order is global atomic commit order. It is authoritative and append-only;
per-actor views are stable filters over that order, never separately reordered
histories. Artifact order is global commit order and then existing declaration
order within a committed step. Mapping normalization remains key-sorted. Failed
attempts appear in schedule/failure evidence, not as committed history.

Actor-aware diagnostics continue to use `scenario.error/1`. Its
`semantic_path`, when available, is the canonical actor or actor-step semantic
address; bounded details may carry safe schedule ordinal and contract identifiers.
No secret seed value, input value, hash preimage, traceback, host path, or raw
plugin exception is disclosed. Stable new error codes require explicit contract
review but do not require a new envelope merely because the semantic path now
uses the already-reserved actor namespace.

`scenario.trace-view/1` remains the renderer contract. It may add an actor-grouped
presentation for supported `scenario.result/2` or `suite.run/2` input only through
an explicitly compatible input-support revision whose output remains bounded,
self-contained, escaped, offline, read-only, and non-executing. The renderer does
not infer missing schedules or replay evidence.

## 10. DSL and engine dispatch

DSL selection occurs before compilation or execution:

| Declared DSL | Execution path | Accepted result/run family |
|---|---|---|
| `1` | Frozen DSL 1 parser/compiler and Engine 1.0.0 compatibility path | `scenario.result/1`, `scenario.manifest/1`, `suite.run/1` |
| `2` | DSL 2 parser/compiler and Engine 2.0.0 logical-concurrency path | `scenario.result/2`, `scenario.manifest/2`, `suite.run/2` |
| Unknown/missing/mixed | Fail closed before execution | None |

Valid DSL 1 documents retain their existing meaning and cannot opt into actors,
schedule seeds, or Engine 2 by package-version inference. DSL 2 does not pass
through or mutate DSL 1 models and then retrofit actors. A document cannot mix
DSL 1 root-step execution with DSL 2 actor execution. Any future serial shorthand
in DSL 2 must lower to an explicit actor before identity and scheduling, but such
syntax is not authorized by this freeze.

Engine 1 and Engine 2 coexist as explicit compatibility paths. Engine 2 does not
replace the frozen Engine 1 implementation and Engine 1 does not accept Engine 2
manifest, result, scheduler, or schedule contracts. Cross-major replay is
supported only where a separately frozen exact route exists; none is inferred.

## 11. Suite, API, and CLI boundaries

`suite.run/2` is the Engine 2 run and replay envelope. It identifies exactly one
`scenario.result/2`/`scenario.manifest/2` execution and its schedule evidence,
or exact immutable references with hashes under a separately approved storage
form. It cannot wrap an Engine 1 child while claiming Engine 2 replay semantics.
`suite.run/1` remains byte- and meaning-stable.

Existing public Python names, signatures, commands, options, streams, exit-code
families, and contract behavior remain compatible for DSL 1 and v1 artifacts.
Phase 5 may add explicit Engine 2 APIs/options only at their checkpoint contract
review; it cannot silently change default dispatch, reinterpret `--seed` as the
schedule seed, or make a schedule seed optional. The existing `run` and `replay`
journey may route by declared artifact/DSL contract while preserving legacy
outputs. A new top-level CLI command is not required by this architecture and is
not authorized here.

## 12. Contract compatibility matrix

| Producer artifact | Consumer/path | Frozen posture |
|---|---|---|
| DSL 1 source | Engine 1 path | Execute with frozen semantics; preserve golden bytes |
| DSL 1 source | Engine 2 actor path | Unsupported; no silent promotion |
| DSL 2 source | Engine 1 path | Unsupported before execution |
| `scenario.result/1` / `scenario.manifest/1` | Existing readers/inspection/diff/migration | Preserve current finite support |
| `scenario.result/1` / `suite.run/1` | Existing supported replay | Preserve exact current behavior |
| v1 artifact | Engine 2 replay | Unsupported unless a future explicit exact route is frozen |
| `scenario.result/2` / `scenario.manifest/2` | Engine 1 reader/replay | Unknown/unsupported; fail closed |
| `scenario.result/2` / `suite.run/2` | Engine 2 exact replay | Supported only with complete exact coordinates |
| Result/manifest of either major | Reader for unknown newer contract | Fail closed; never silently upgrade |
| Phase 4 durable contracts | Phase 5 tools | Preserve contract versions and existing semantics |

This matrix preserves legacy deterministic goldens and supported replay while
making no promise of universal cross-major execution.

## 13. Security and resource model

All Phase 1–4 trust boundaries remain mandatory: safe YAML, explicit bounded
local inputs, no-follow path handling, regular files, explicit roots, absent
destinations, atomic publication, canonical bytes, immutable evidence, exact
hash verification, secret redaction, and fail-closed unknown versions. Explicit
Python plugins remain trusted and unsandboxed but receive no scheduler,
filesystem, network, process, environment, or wall-clock authority from Phase 5.

### 13.1 Phase 5 hard ceilings

The following values are public contract commitments for DSL 2 and Engine 2.
Every ceiling is an independent, inclusive maximum: a value equal to its ceiling
is permitted, while a value greater than any applicable ceiling is rejected.
MiB means 1,048,576 bytes. Counts are exact nonnegative integer counts and byte
counts are over the complete canonical compact UTF-8 serialization named below.

| Public limit | Inclusive ceiling | Unit and counted quantity | Enforcement boundary |
|---|---:|---|---|
| `MAX_ACTORS` | 32 | actor declarations in one DSL 2 scenario | Static parse/model validation, before compilation or execution |
| `MAX_STEPS_PER_ACTOR` | 256 | statically declared flow nodes owned by one actor | Static parse/model validation |
| `MAX_TOTAL_DECLARED_STEPS` | 4,096 | statically declared flow nodes summed across all actors | Static parse/model validation |
| `MAX_SCHEDULER_SELECTIONS` | 65,536 | attempted scheduler selections in one run, including a final failed attempted selection | Dynamic, checked before creating the next selection record or executing its transition |
| `MAX_CONTROL_ROUTING_OPERATIONS_PER_SELECTION` | 4,096 | deterministic control-routing operations used to locate one selected actor's next executable step | Dynamic, checked during routing and before transition execution |
| `MAX_CANONICAL_SCHEDULE_BYTES` | 8,388,608 (8 MiB) | canonical `scenario.schedule/1` payload bytes used for schedule identity, with `schedule_hash` omitted as specified in Section 8 | Checked during bounded construction and before acceptance, publication, or replay use |
| `MAX_CANONICAL_RESULT_BYTES` | 33,554,432 (32 MiB) | complete canonical `scenario.result/2` bytes | Checked during bounded construction and before a result is returned or published |
| `MAX_REPLAY_SCHEDULER_SELECTIONS_VERIFIED` | 65,536 | recorded scheduler selections verified by one exact replay operation | Replay preflight where determinable, and incrementally before verification of each next record |

A **declared flow node** is one uniquely identified node written in an actor's
root flow or actor-owned subflow, whether the node is an executable step or a
control node such as a call, branch, or repeat. A declaration is counted exactly
once in its owning actor and once in the scenario aggregate. Declaration counts
do not count repeat iterations, subflow invocations, scheduler selections,
committed history events, failed attempts, or any other runtime event. Sharing or
invoking one declared subflow multiple times does not duplicate its declaration
count. No actor may borrow unused capacity from another: both the per-actor and
aggregate ceilings apply.

A **scheduler selection** is one scheduler decision record, starting at ordinal
zero, whether its selected transition later commits or fails. It is not a
declared step count: loops and repeated visits can cause many selections of the
same declared step. A **control-routing operation** is one deterministic routing
action: inspecting a flow node, evaluating one ordered branch condition,
entering or returning from a subflow invocation, initiating or advancing one
repeat iteration, or following one control transition. Implementations must use
this logical definition and cannot make the count depend on Python operations,
CPU instructions, elapsed time, recursion strategy, caching, or host behavior.
The routing counter resets for each selection; the scheduler-selection counters
do not reset during a run or replay.

Static limits are rejected before execution and before allocation proportional
to an over-limit declaration where practical. Dynamic limits are checked before
the operation that would make the count exceed the ceiling. Schedule and result
byte limits must be enforced with bounded accounting during construction, not by
first creating an unbounded object. If several limits would reject at the same
defined validation point, the eventual contract must freeze deterministic error
precedence.

All resource-limit failures fail closed through the existing
`scenario.error/1` envelope with a stable reviewed code, safe semantic path when
available, applicable public limit name and ceiling, and no secret-bearing value.
There is no silent truncation, clamping, actor omission, schedule-prefix success,
partial result, partial replay success, or partial publication. A failed
transition retains the atomicity rules in Sections 5 and 6. Lower explicit
operation limits may be offered only when their names, values, and failure
behavior are public and deterministic; no default, configuration, plugin, API,
CLI option, or environment value may raise a hard ceiling or do so silently.

### 13.2 Preserved limits and compatibility

The existing `scenario.semantic-address/1` maximum depth of 32
kind/identifier pairs and maximum canonical serialized length of 2,048 UTF-8
bytes remain unchanged. Actor activation does not increase, weaken, reinterpret,
or silently truncate either limit; an actor or actor-step address must satisfy
the same normalization and canonicality rules as every other address.

The existing `scenario.error/1` ceilings remain unchanged: one canonical error
envelope is at most 1 MiB, nesting depth is at most 32, and `details` contains at
most 1,000 entries. Existing narrower field, detail-key, and presentation bounds,
deterministic ordering, truncation disclosure where the frozen diagnostic
contract permits presentation truncation, and secret redaction remain
authoritative. Phase 5 requires no additional diagnostic ceiling.

DSL 1 remains on its frozen parser/compiler and Engine 1 path. In particular,
its repeat maximum of 100, its accepted declarations, and its existing
execution, history, artifact, provenance, reader, canonicalization, CLI, and
result/evidence limits retain their current meanings. The new actor, declaration,
selection, routing, schedule-byte, Result/2-byte, and replay-verification ceilings
apply only to DSL 2/Engine 2 contracts and cannot reject an input previously
supported by DSL 1. Existing cross-product limits remain independently
applicable where their frozen contract consumes an Engine 2 artifact; wrapping,
inspection, trace rendering, suite orchestration, or evidence export cannot
increase a native Phase 5 ceiling.

These finite ceilings bound parser/model allocation, scheduler work, cyclic or
adversarial control routing, schedule-evidence growth, canonicalization memory,
result retention, and replay verification of untrusted evidence. They prevent a
small declaration, repeat, or hostile schedule from causing unbounded CPU or
memory consumption while keeping counts independent of machine speed and host
configuration. Runtime-dependent limits are architectural constraints only in
this amendment; no scheduler or other Phase 5 implementation is authorized.

The engine performs no network calls, remote retrieval, runtime LLM calls,
distributed coordination, subprocess scheduling, dynamic code loading from DSL,
or ambient environment discovery. Schedule artifacts are untrusted input;
reading and inspection are bounded and non-executing. Replay executes only after
all applicable compatibility and integrity gates pass.

## 14. Architecture decision register

| Decision | Frozen resolution | Status |
|---|---|---|
| Actor identity and ordering | Unique names; canonical `scenario:/actor/<id>` identity; bytewise canonical-address ordering | Accepted |
| Actor-local versus shared state | One shared logical state; locals are transition-local; actor position is engine control state | Accepted |
| Atomic transition boundary | One whole executable step; no yield or interleaving inside it | Accepted |
| Readiness and termination | Finite deterministic routing; terminal only when all actors terminal; nonterminal empty-ready set fails closed | Accepted |
| Schedule seed and selection | Independent required seed; exact `scenario.scheduler/1` SHA-256 coordinate algorithm | Accepted |
| Schedule hash and replay | `scenario.schedule/1`; hash of canonical schedule payload; replay verifies every ready set and selection | Accepted |
| Failure/fault/invariant ordering | Existing step order retained; failed transition commits no scenario mutation; attempted selection remains evidence | Accepted |
| History and normalization | Global commit order with actor addresses; per-actor views are filters; new `scenario.result/2` | Accepted |
| DSL dispatch | Declared integer 1 uses frozen path; integer 2 uses actor path; mixed/unknown fails closed | Accepted |
| Engine compatibility | Engine 1.0.0 retained; Engine 2.0.0 is a separate future path | Accepted |
| Result boundary | Result/1 unchanged; Result/2 required for actor/schedule evidence | Accepted |
| Suite versioning | `suite.run/1` unchanged; `suite.run/2` required for Engine 2 replay envelope | Accepted |
| Resource bounds and security | Public inclusive DSL 2/Engine 2 ceilings frozen in Section 13; inherited limits preserved; local, bounded, redacted, no network/LLM/distributed authority | Accepted |
| Existing CLI/API | Preserve legacy signatures/behavior; additive Engine 2 surface requires checkpoint review | Accepted |

No frozen Phase 1–4 contract materially conflicts with this architecture. The
new major contracts are required precisely to avoid reinterpreting frozen v1
contracts. The Phase 4 `actor` semantic-address reservation is compatible and is
activated only for new Phase 5 producers.

## 15. Checkpoint sequence and acceptance gates

Each checkpoint requires all predecessor gates, localized changes, targeted
tests, deterministic fixtures, security review appropriate to its surface,
documentation, `git diff --check`, no unintended legacy-byte changes, and a
clean committed evidence record. Passing one checkpoint does not authorize the
next.

| Checkpoint | Bounded objective | Explicit acceptance gate |
|---|---|---|
| **5.1 — Versioned actor and DSL 2 models** | Immutable actor declarations, identity, strict DSL 2 parse/compile dispatch, frozen bounds | Exact 32 actors, 256 nodes/actor, and 4,096 aggregate nodes pass; each ceiling plus one fails before execution; per-actor and aggregate counts are independent; DSL 1 parser/goldens unchanged; duplicate/invalid actors and mixed DSL fail closed; canonical actor addresses pass Phase 4 rules |
| **5.2 — Engine 2 step-atomic kernel** | Shared state/clock and actor positions with one-step commit boundary | Serial reference cases prove no partial mutation, one shared clock, immutable committed history, and no host concurrency semantics |
| **5.3 — Deterministic scheduler** | `scenario.scheduler/1`, ready-set construction, independent schedule seed | Literal scheduler vectors across actor order/process runs; root-seed/schedule-seed isolation; exactly 65,536 selections and 4,096 routing operations/selection pass, plus one fails before excess work or transition; counts are host-independent; stall behavior passes |

### 5.3 internal actor coordinator implementation boundary

The Phase 5.3 implementation integrates validated DSL 2 actor declarations with
the frozen pure scheduler through an internal, non-exported coordinator. It owns
one shared scenario state, logical clock, committed history, and artifact list,
while immutable actor control stacks remain separate engine state. Readiness is
recomputed by bounded, mutation-free routing before every zero-based selection;
the selected actor then completes one whole existing transition candidate and
commit boundary. All-terminal completion succeeds, a nonterminal empty-ready set
fails closed, and transition failure stops execution without state, clock,
history, artifact, or actor-position commit. The coordinator's immutable outcome
is test-only internal data and is not a `scenario.schedule/1`, `scenario.result/2`,
`scenario.manifest/2`, or `suite.run/2` artifact.
| **5.4 — Schedule evidence and identity** | `scenario.schedule/1`, canonical records and schedule hash | Canonical-byte/hash vectors; exactly 8 MiB passes and one byte over fails without partial evidence; attempted/committed outcome rules, tamper rejection, immutable bounded evidence pass |
| **5.5 — Result and manifest v2** | `scenario.result/2` and `scenario.manifest/2` normalization | Exact schema/round-trip/golden vectors; exactly 32 MiB passes and one byte over fails without a partial result; actor/history/artifact order; no Result/1 or Manifest/1 byte drift |
| **5.6 — Exact schedule replay** | Verify complete Engine 2 coordinates and each recorded selection | Positive exact-byte replay; exactly 65,536 verified selections pass and plus one fails before excess verification or execution; scenario/input/actor/ready-set/selection/seed/version/hash mismatches fail before mismatched commit |
| **5.7 — Suite run v2 and orchestration** | `suite.run/2` envelope and finite compatibility reporting | Run/2 round trips and replay links; Run/1 unchanged; mixed-major and incomplete envelopes fail closed |
| **5.8 — Actor-aware diagnostics and inspection** | Safe errors, inspect/explain/diff support for v2 evidence | Actor semantic paths, finite codes, deterministic ordering, redaction, unavailable-not-invented behavior, v1 regressions pass |
| **5.9 — Actor-aware static trace viewing** | Offline bounded actor grouping from supported v2 evidence | Self-contained CSP-safe escaped output; no execution/network/mutation; deterministic actor/global views; v1 viewer behavior preserved |
| **5.10 — Public API/CLI and compatibility fixtures** | Explicit additive Engine 2 entry surface and immutable cross-version fixtures | Existing APIs/CLI journeys remain compatible; schedule seed is explicit; fixture integrity and full compatibility matrix pass |
| **5.11 — Performance, security, and contract freeze** | Enforce ceilings, adversarial replay/evidence tests, final public contracts | Resource ceilings, deterministic limit failures, tamper/path/secret tests, legacy goldens, docs and fresh-install targeted gates all pass |
| **5.12 — Independent acceptance and DSE 3.0.0 publication** | Independent candidate verification, then separately authorized tag/package/release | Candidate SHA/artifact hashes, clean source, supported Python matrix, replay/security acceptance, explicit publication authorization, immutable release verification |

The tentative publication target for DSE `3.0.0` is **December 15, 2026**. It
is a planning target, not an authorization or guarantee. Publication cannot occur
before 5.12 gates and a separate explicit release decision.

## 16. Phase 5 acceptance criteria

Phase 5 may be accepted only when all of the following are demonstrated:

1. named logical actors interleave only at whole-step boundaries over one shared
   state and logical clock;
2. scheduler vectors depend only on frozen canonical coordinates and the
   independent schedule seed;
3. canonical schedule identity and exact replay detect every required coordinate
   mismatch before unsafe commit;
4. actor-aware history, diagnostics, inspection, diff, and trace presentation are
   deterministic, bounded, immutable, and secret-safe;
5. DSL 1, Engine 1.0.0, Result/1, Manifest/1, Suite Run/1, supported replay,
   Phase 4 contracts, and all frozen legacy golden bytes remain unchanged;
6. unknown or unsupported contracts fail closed and no historical artifact is
   silently upgraded;
7. filesystem/evidence integrity and deterministic RNG/ID guarantees remain
   intact;
8. no network, runtime LLM, real-threading semantics, distributed authority, or
   excluded schedule-exploration feature enters the product; and
9. independent release acceptance and explicit publication authorization pass.

Resource-bound acceptance additionally requires boundary and boundary-plus-one
tests for every Section 13 ceiling; independent per-actor and aggregate
declaration tests; declaration-versus-runtime-selection tests using repeat or
revisit behavior; static rejection before execution; dynamic rejection before
the excess operation; exact canonical byte accounting with multibyte UTF-8;
deterministic error precedence; no truncation or partial success; secret-safe
`scenario.error/1` failures; unchanged semantic-address and diagnostic vectors;
and unchanged DSL 1 accepted inputs, limits, result bytes, and replay behavior.

## 17. Phase 5.0 exit gate and mandatory stop

This architecture-freeze checkpoint passes when the exact entry baseline and
repository state are verified, this is the only repository path changed,
targeted contract consistency checks and `git diff --check` pass, a
documentation-only commit is pushed without force, final `HEAD`, `main`, and
`origin/main` agree with a clean worktree, and one external evidence file records
the immutable result.

```text
PHASE5_0_ARCHITECTURE_FREEZE_COMPLETE=YES
PHASE5_1_IMPLEMENTATION_AUTHORIZED=NO
PRODUCTION_CODE_CHANGE_AUTHORIZED=NO
CURRENT_VERSION_CHANGE_AUTHORIZED=NO
RELEASE_PUBLICATION_AUTHORIZED=NO
NEXT_ACTIVITY=MANDATORY_STOP
```

Successful scope freeze is not implementation authorization. Do not implement
Phase 5.1, change production code, change current version values, or publish a
release as part of this checkpoint.
