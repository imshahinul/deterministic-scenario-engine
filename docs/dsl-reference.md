# DSL 1 reference

This reference describes the frozen Scenario Engine DSL 1 grammar and semantics.
Unknown keys are rejected in every schema-defined mapping.

## Root document

Required root keys are:

| Key | Shape | Meaning |
| --- | --- | --- |
| `dsl_version` | integer `1` | DSL contract selector; boolean `true` is invalid |
| `scenario` | nonempty string | scenario ID |
| `clock` | `{start: <aware ISO-8601 string>}` | reference logical clock, normalized to UTC |
| `initial_state` | mapping | initial semantic state |
| `steps` | nonempty ordered list | root execution sequence |

Optional root keys are `resources`, `validators`, `constraints`, `subflows`,
`invariants`, `faults`, and `oracle`.

An executable step requires `id` and `transition`; it may contain `generate`,
`derive`, `write`, `emit`, and `advance`. A control node requires `id`, exactly
one of `call`, `branch`, or `repeat`, and `transition`; executable fields cannot
be mixed with a control field. Node IDs are globally unique across root and
subflow sequences. The root list and every subflow step list must be nonempty.

## Scenario Engine DSL 1 YAML source contract

DSL input is safely loaded YAML with deliberately narrow source rules; it is not
advertised as generic YAML 1.2 compliance.

- duplicate mapping keys are rejected at every depth;
- aliases are rejected;
- merge keys are rejected;
- arbitrary/custom YAML tags are rejected;
- plain `true` and `false` are booleans;
- legacy `yes`, `no`, `on`, and `off` spellings remain strings;
- integers use narrow decimal syntax: `0` or optional `-` followed by a nonzero
  decimal digit and decimal digits;
- ambiguous legacy integer forms remain strings;
- YAML/Python floats are rejected at semantic boundaries; use `$decimal`;
- semantic mapping keys must be strings; and
- standard YAML null spellings resolve to null.

## Semantic typed values

Direct semantic values are null, string, boolean, integer, list, and string-keyed
mapping. Additional values use one-key wrappers:

```yaml
money: {$decimal: "19.95"}                 # finite Decimal
instant: {$datetime: "2026-01-01T12:00:00Z"} # aware datetime, normalized UTC
delay: {$duration: {seconds: 30}}          # duration with exact integer seconds
absent: {$missing: true}                   # MISSING, distinct from null
```

Nested lists and mappings may contain all semantic types. `$id` generation
produces a `LogicalID`, a deterministic semantic atom whose normalized form is
stable. Explicit semantic floats, non-finite decimals, naive datetimes, and
unsupported Python objects are invalid.

## Generators

Generators appear under `generate` and create invocation-local names:

- `{$int: [lower, upper]}` — addressed integer in inclusive exact-integer bounds;
- `{$id: namespace}` — addressed `LogicalID` in a nonempty namespace;
- `{$literal: value}` — exact semantic value; and
- `{$plugin: {name: ..., version: ..., args: {...}}}` — explicitly registered,
  exact-version plugin; `args` is optional and each value is a control-safe
  expression. See [plugins](plugins.md).

Generation names are visible through `$local` in the same executable step.

## Expressions and namespaces

Every expression is a one-key mapping. References are:

- `{$state: name}` — pre-state in derives/writes; candidate post-state in emit
  fields;
- `{$local: name}` — current step generated local;
- `{$derived: name}` — current step derived value;
- `{$resource: dotted.path}` — resolved resource value;
- `{$scope: dotted.path}` — current subflow invocation binding; and
- `{$literal: value}` — explicit semantic value.

Derived declarations form a dependency DAG and may refer to other derived names;
cycles are rejected. `$local` and `$derived` are unavailable at control
boundaries. Invariants permit state/resource/literal operations but reject local,
derived, and scope references. Constraints reject state/local/derived references.

Operators:

| Operator | Payload and result |
| --- | --- |
| `$add`, `$sub`, `$mul`, `$div` | exactly two numeric expressions |
| `$eq`, `$ne` | exactly two expressions; canonical semantic equality |
| `$lt`, `$lte`, `$gt`, `$gte` | exactly two compatible numbers, strings, or aware datetimes |
| `$and`, `$or` | nonempty ordered expression list; every result exactly boolean |
| `$not` | one expression whose result is exactly boolean |
| `$len` | string, list/tuple, or mapping; returns integer |
| `$append` | `{list: <expr>, value: <expr>}`; returns a new list |
| `$object` | mapping of field names to expressions; returns an object |
| `$sum_field` | `{source: <expr>, field: <name>}`; sums numeric fields |

Emission field expressions are deliberately restricted to `$state`, `$resource`,
and `$literal`.

## Arithmetic

Arithmetic accepts only integers excluding booleans and finite `Decimal` values.
For `$add`, `$sub`, and `$mul`, int/int returns int; Decimal participation returns
Decimal. `$div` always returns Decimal and zero division is an expression error.
All Decimal arithmetic uses an explicit context with precision 28 and
`ROUND_HALF_EVEN`; the ambient process Decimal context cannot affect results.
Strings, lists, booleans, null, `MISSING`, durations, and arbitrary Python
operator overloads are not arithmetic operands.

## Write semantics

Each `write` key names one top-level state field and its expression supplies the
complete replacement value. Writes are shallow top-level replacements—not deep
merge and not dotted/path updates. To alter a nested value, construct and write
the complete replacement top-level value supported by the available expressions.

All write expressions observe pre-state, generated locals, and resolved derives;
the resulting patch is applied together to form candidate post-state.

## Emit and artifacts

`emit` is an ordered list of `{type, fields}` declarations. Declaration order is
semantic and becomes artifact order. Emission `$state` references read candidate
post-state, so an artifact can report values written by its step. Artifact IDs
and addresses are deterministic. Emissions are candidates until the entire step
commits; a failed step emits nothing.

## Resources and external inputs

Resources form a mapping resolved before execution:

- `{$input: dotted.path}` reads an explicitly supplied input;
- `{$ref: dotted.path}` reads another resource, forming a dependency DAG;
- `{$literal: value}` protects a literal mapping/value where needed.

Dependencies are resolved deterministically; missing paths and cycles fail.
Validators and constraints run after enabled `before_validation` resource faults
and before executable steps. The manifest hashes consumed input values and each
resolved resource. Unused supplied input keys are not consumed and therefore do
not affect result or manifest bytes.

## Validators

Validators are an ordered list. Each requires unique `id`, resource path, and
kind:

- `required` — value must not be `MISSING`;
- `type` — one of `integer`, `decimal`, `boolean`, `string`, `null`, `datetime`,
  `duration`, `logical_id`, `list`, `map`, or `missing`;
- `range` — inclusive numeric `min` and/or `max`;
- `length` — inclusive nonnegative integer `min` and/or `max` for sized values;
- `one_of` — nonempty `values` list using semantic equality.

## Constraints

Constraints are an ordered list of `{id, check, message?}`. They run once after
resource resolution, resource faults, and validation, but before scenario-step
execution. Each check must return exactly boolean; false raises a constraint
violation. The optional message is a string. Constraint expressions may use
resources and literals but not execution state, locals, or derives.

## Subflows and call

`subflows` maps a name to `{steps: [...]}`. A call node is:

```yaml
- id: call_payment
  call:
    subflow: payment
    with: {customer_id: {$resource: customer.id}}
  transition: next_root_node
```

`with` is optional. It evaluates explicit bindings at the control boundary and
creates invocation-local `$scope`. Scope is not inherited implicitly: callers
must explicitly forward a value to a nested invocation. Recursive subflow call
graphs are rejected during compilation.

## Branch

A branch contains a nonempty ordered `cases` list. Each case has `when`,
`subflow`, and optional `with`; optional `else` has `subflow` and optional `with`.
Conditions must evaluate to exactly boolean. The first true case is invoked. If
none matches, `else` is invoked when present; no match and no `else` is a
deterministic no-op before the node's root transition.

## Repeat

A repeat requires `count`, literal `max`, `subflow`, and optionally `with` and
`index_as`. `count` must evaluate to an exact nonnegative integer (booleans are
not integers here) no greater than `max`. `max` itself must be an integer from 0
through the engine maximum supported bound, 100. Count zero performs no
invocations. `index_as` exposes each zero-based index in invocation `$scope` and
must not collide with an explicit `with` binding. Each iteration extends the
execution address with deterministic invocation and repetition components.

## Invariants

Invariants are ordered `{id, check}` declarations. After a step constructs
candidate post-state, every invariant check evaluates against that candidate.
The result must be exactly boolean. A false invariant aborts the whole step:
state, history, artifacts, transition, and logical-clock advance do not commit.

## Faults

Faults are ordered and disabled by default. Each has `id`, `enabled`, `at`, an
operator, optional expected violations, and `strict_unexpected` (default true).

Hooks and operations are:

- `before_validation`: `override_resource: {path, value}`;
- `before_step`: `override_write: {path, value}`;
- `before_step`: `override_local: {name, value}`;
- `before_step`: `suppress_emissions: true`.

A before-step `selector` requires `step` and may restrict `subflow_path` and
`repetition_indexes`. The selected step/write/local must be declared. Matching
enabled faults apply in declaration order and are recorded in deterministic
provenance/history. Faults model only these engine execution points.

## Oracle

`oracle.expected` contains constraint and invariant ID lists;
`strict_unexpected` defaults true. `evaluate_scenario()` observes at most the
resource constraint violation or candidate-state invariant violation reached by
execution, merges expectations from applied faults without duplicates, and
reports unexpected and missing expectations. In strict mode unexpected observed
violations fail evaluation; missing expectations always fail. With
`raise_on_mismatch=True`, a failed report raises `OracleMismatchError`.

See [testing and oracle](testing-oracle.md) for a complete example.

## Empty declarations

Compatibility-frozen behavior is asymmetric:

- explicitly empty `validators`, `invariants`, and `faults` lists are accepted;
- explicitly empty `resources`, `constraints`, and `subflows` are rejected; and
- empty `oracle.expected.constraints` and `oracle.expected.invariants` lists are
  accepted.

Omitting any optional declaration uses its empty/default behavior.

## Unsupported syntax and non-goals

Unknown root/node/expression/generator keys, arbitrary tags/Python, recursive
subflows, unbounded loops, deep path writes, and implicit external services are
unsupported. See [security assumptions and non-goals](security-and-non-goals.md).
