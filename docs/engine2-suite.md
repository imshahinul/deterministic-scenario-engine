# Engine 2 serial suite contract

This document defines the accepted `scenario.engine2-case/1`,
`scenario.engine2-suite-plan/1`, and `scenario.engine2-suite/1` contracts included
in the 3.1.0 release candidate. They are additive and module-qualified. Existing
Result/2, Manifest/2, Schedule/1, Scheduler/1, historical Suite Run/2, Engine 1,
Engine 2 compatibility version 2.0.0, and package-root exports are unchanged.

## Scope and API

The API is available only from `scenario_engine.engine2_suite`:

* `Engine2CaseRequest`, `Engine2SuitePlan`, `Engine2CaseOutcome`, and
  `Engine2SuiteOutcome`;
* `execute_engine2_suite(plan)`;
* `read_engine2_suite(source)`; and
* `verify_engine2_suite(suite, child_evidence=None)`.

Execution is finite, serial, and exactly plan ordered. It accepts only already
validated `CompiledScenarioV2` values and explicit independent `root_seed` and
`schedule_seed` coordinates. It does not explore schedules, execute remotely,
run in parallel, discover plugins, access a network, or support cross-major
execution. Plugins are explicit trusted, unsandboxed Python and are not a
security boundary.

## Limits

The initial hard limits are deliberately smaller than the native per-run and
older batch ceilings:

| Limit | Value |
| --- | ---: |
| cases per plan | 64 |
| canonical supplied inputs per case | 262,144 bytes |
| aggregate canonical supplied inputs | 4,194,304 bytes |
| canonical case request coordinates | 524,288 bytes |
| aggregate canonical case request coordinates | 1,048,576 bytes |
| input nesting depth | 32 |
| native selections per case | 65,536 |
| aggregate native selections | 262,144 |
| retained Result/2 + Manifest/2 + Schedule/1 bytes | 67,108,864 bytes |
| canonical suite aggregate | 2,097,152 bytes |
| canonical error record | 512 bytes |
| case identifier UTF-8 bytes | 128 bytes |

The 64-case, 64 MiB retained-evidence, and 2 MiB aggregate limits keep a suite
reviewable and prevent the architecture proposal's unqualified 1,000-case and
4 GiB values from becoming accidental commitments. Bounds are checked before
case execution when knowable and incrementally before evidence retention.
Integers exclude booleans. Exceeding a plan/input bound rejects the entire plan;
exceeding a runtime aggregate selection or retention bound records a redacted
case `ERROR` and continues only when safe. Nothing is silently truncated or
represented as success. Plans must be explicit ordered sequences; generators
and unordered containers are rejected before materialization. Input nesting is
checked before normalization and immutable copying. A native Result/2 or
Schedule/1 construction/serialization defect aborts the suite rather than
discarding authoritative evidence and continuing with a misleading case record.
The aggregate supplied-input limit is enforced against the sum of every case
request's declared `input_bytes` during plan construction, aggregate object
construction, strict canonical reading, and independent offline verification.
Each declaration remains subject to its per-case limit; an aggregate containing
individually valid declarations is rejected when their sum exceeds 4,194,304.

## `scenario.engine2-case/1`

The canonical case identity payload has exactly these required fields:

* `contract`: literal `scenario.engine2-case/1`;
* `position`: nonnegative integer equal to the containing list index;
* `case_id`: unique portable ASCII label matching
  `[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}`;
* `scenario_hash`: existing canonical scenario SHA-256;
* `root_seed`: explicit string or integer, excluding boolean;
* `schedule_seed`: explicit integer in `0..2^64-1`, excluding boolean;
* `run_index`: explicit nonnegative integer, excluding boolean;
* `input_hash`: SHA-256 of canonical bytes for the complete supplied input
  mapping, including unused supplied inputs;
* `input_bytes`: byte length of those canonical input bytes;
* `input_resource_hashes`: authoritative hashes from existing resource
  resolution for the effective inputs;
* `plugin_versions`: sorted explicit registry name-to-version mapping;
* `reference_clock_start`: canonical timezone-aware semantic datetime,
  normalized to UTC by the existing native Engine 2 clock rule;
* `generator_versions`: existing generator requirements, including declared
  plugin requirements;
* `domain_pack_versions`: explicit empty mapping;
* `dsl_version`, `engine_version`, `result_contract`, `manifest_contract`,
  `schedule_contract`, `scheduler_contract`, `execution_model`,
  `rng_algorithm_version`, `id_algorithm_version`, and `locale`: the exact
  supported tuple `2`, `2.0.0`, `scenario.result/2`, `scenario.manifest/2`,
  `scenario.schedule/1`, `scenario.scheduler/1`, `logical-actors/1`, current
  RNG/ID versions, and `C`; and
* `expectation`: an exact object with `classification` (`SUCCESS` or `FAILED`)
  and `failure_code` (null for `SUCCESS`, otherwise a nonempty stable code).

`case_identity` is lowercase SHA-256 of canonical bytes for that complete
payload. The in-memory request accepts convenience defaults for `run_index=0`,
empty inputs, no plugin registry, and expected success; construction converts
them into every explicit canonical coordinate above. Scenario and plugin Python
objects are excluded from serialized evidence. Resource identities are resolved
before execution; no pre-execution identity is fabricated. Registry entries
must exactly satisfy every declared plugin name/version. Plugin callables are
never invoked by plan validation.

## Plan identity

An `Engine2SuitePlan` contains 1..64 unique case IDs and unique case identities.
It assigns positions in request order and validates every case before any case
executes. Its exact canonical plan identity payload is:

```text
{"case_identities":[...],"contract":"scenario.engine2-suite-plan/1",
 "limits":{"aggregate_input_bytes":4194304,"aggregate_selections":262144,
 "canonical_suite_bytes":2097152,"cases":64,"error_bytes":512,
 "input_bytes_per_case":262144,"request_bytes_per_case":524288,
 "request_bytes_total":1048576,"retained_child_bytes":67108864,
 "selections_per_case":65536}}
```

where the shown object is canonically encoded without whitespace and the
identity list is plan ordered. `plan_hash` is SHA-256 of those canonical bytes.
All limit fields are mandatory identity-bearing coordinates; there are no
serialized implicit defaults.

## `scenario.engine2-suite/1`

The canonical suite object has exactly these required fields:

* `contract`: literal `scenario.engine2-suite/1`;
* `plan`: exact object containing `contract`, ordered `case_identities`, exact
  `limits`, and `plan_hash`;
* `cases`: ordered case outcome records;
* `counts`: exact object containing integer `success`, `expected_failure`,
  `unexpected_failure`, `error`, and `total`;
* `status`: `SUCCESS` only when every case is `SUCCESS` or
  `EXPECTED_FAILURE`, otherwise `FAILED`; and
* `aggregate_hash`: SHA-256 of canonical bytes for all preceding fields.

Each case outcome record has exactly `request`, `case_identity`, `status`,
`observed`, `native`, and `error`. `request` is the complete case identity
payload. `status` is one of `SUCCESS`, `EXPECTED_FAILURE`,
`UNEXPECTED_FAILURE`, or `ERROR`. `observed` is exactly
`{"classification": "SUCCESS"|"FAILED"|null, "failure_code": string|null}`.

For a completed native execution, `native` is an object with `result`,
`manifest`, and `schedule`. Every reference has exactly `contract`, `identity`,
`sha256`, and `size`: `identity` is the native result/manifest/schedule hash,
while `sha256` hashes the complete exact canonical artifact bytes. For an
execution error without retained authoritative native evidence, `native` is
null; child hashes are never invented.

`error` is null unless status is `ERROR`. An error is exactly `stage`, `family`,
`code`, and `message`. The complete accepted combinations are:

| Stage | Family | Code | Fixed message |
| --- | --- | --- | --- |
| `preflight` | `VALIDATION` | `CASE_VALIDATION_FAILED` | `case validation failed` |
| `execution` | `PLUGIN` | `PLUGIN_EXECUTION_FAILED` | `trusted plugin execution failed` |
| `execution` | `INTERNAL` | `INTERNAL_EXECUTION_FAILED` | `case execution failed` |
| `retention` | `LIMIT` | `CHILD_EVIDENCE_BOUND_EXCEEDED` | `retained child evidence bound exceeded` |
| `retention` | `LIMIT` | `SELECTION_BOUND_EXCEEDED` | `aggregate scheduler selection bound exceeded` |

No cross-combination is valid. Plan construction normally rejects validation
defects before execution; the preflight row reserves the only stable redacted
record shape for a safely isolated case-validation failure. Unknown fields,
codes, stages, families, altered messages, child references on an `ERROR`, and
non-null observations on an `ERROR` are invalid. Exception text, paths, supplied
values, plugin arguments, private inputs, and secrets are never serialized.

A normal successful Result/2 matches only a declared `SUCCESS`. A native failed
Result/2 always remains classified `FAILED`. It becomes suite status
`EXPECTED_FAILURE` only when the declaration is `FAILED`, its failure code
exactly equals both Result/2 and Schedule/1 failure codes, and the raised error
is a recognized deterministic `InvariantViolation` with the same authoritative
`internal_outcome`. Every other native failure is `UNEXPECTED_FAILURE`.
Validation, plugin, limit, and unrecognized exceptions can never satisfy an
expected-failure declaration. The supported expected-failure code set contains
only `InvariantViolation`; it is not expanded by a matching arbitrary string.
Every completed native observation other than expected success or that one
supported expected invariant failure is `UNEXPECTED_FAILURE`. The strict reader
enforces this status matrix. Because exception objects are not serialized, an
offline reader can validate the stable code and native linkage but cannot prove
that Python exception provenance was truly `InvariantViolation`; that stronger
claim belongs to trusted execution or exact replay.

## Strict reading and verification

`read_engine2_suite` accepts bounded UTF-8 canonical bytes only. It rejects
duplicate JSON keys, noncanonical bytes, excess nesting, unknown or missing
fields, unsupported contracts/versions, bool-as-int values, bad hashes,
duplicate IDs/identities, positions not equal to list indexes, malformed status
combinations, malformed or noncanonical datetime wrappers, naive or non-datetime
reference clocks, aggregate declared-input overflow, and inconsistent
counters/status. Unhashable or incorrectly typed status/error fields produce
stable suite-validation errors rather than escaping lookup exceptions. It
reconstructs no scenario or plugin objects.

`verify_engine2_suite` independently rechecks suite identities and accepts
bounded child bytes supplied in memory as
`{case_id: {"result": bytes, "manifest": bytes, "schedule": bytes}}`. It uses
the existing strict native readers, validates exact byte size/SHA-256/native
identity, verifies Manifest/2 equals the manifest embedded by Result/2, and
checks every scenario/resource/seed/run/version/classification/failure and
Result/2-to-Schedule/1 relationship. Missing, swapped, duplicated, incompatible,
or tampered evidence fails closed. No filesystem publication or resolver is
introduced.

The verification boundary has four distinct layers:

1. **Canonical aggregate integrity:** strict shape, bounds, canonical bytes,
   status/count semantics, plan identity, case identities, and aggregate hash.
2. **Native child artifact integrity:** exact byte lengths and SHA-256 values,
   strict native readers, and native Result/2, Manifest/2, and Schedule/1
   identities.
3. **Cross-artifact coordinate linkage:** scenario, effective-resource hashes,
   explicit seeds, run index, clock, versions, classification, failure, and
   Result/2-to-Schedule/1 references agree.
4. **Actual scenario replay:** execution of the exact scenario with its effective
   original inputs and trusted plugin registry through existing `replay_engine2`.

`verify_engine2_suite` establishes A-C only; it never claims or performs D. It
executes no scenario, plugin, network request, or external command. Supplied-input
hash and byte length are identity coordinates for the complete supplied mapping,
including unused values; effective-resource hashes separately link the resolved
resource snapshot. The original supplied/effective inputs may therefore be
required separately for exact replay. Plugin registry name/version identity does
not prove correctness or safety of untrusted Python callables. Likewise, a
canonical `ERROR` record proves only that the aggregate contains an allowed
redacted claim; offline verification cannot prove an actual execution exception
occurred. Exact replay is separate and requires the exact scenario, inputs, and
trusted registry for each complete case. Suite Run/2 is neither produced nor
reinterpreted because partial cases and duplicate native result identities cannot
always satisfy its frozen uniqueness/completeness semantics.
