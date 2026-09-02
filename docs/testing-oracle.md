# Testing, invariants, faults, and oracle

Scenario Engine produces deterministic ground truth: state, committed history,
artifacts, violations, fault provenance, and replay context—not merely generated
records.

## Candidate-state invariants and atomic failure

Each invariant is evaluated after the complete write patch forms candidate
post-state and before commit. A false result raises an invariant violation. The
candidate step contributes no state mutation, history record, artifact, clock
advance, or transition. Earlier committed steps remain observable.

Resource constraints run earlier: after resources resolve, enabled resource
faults apply, and validators pass, but before step execution. Checks for both
constraints and invariants must return exactly `bool`; truthy non-booleans are
definition errors.

## Fault injection

Implemented deterministic execution points are limited to:

- `before_validation` resource-value override;
- `before_step` generated-local override;
- `before_step` write-value override; and
- `before_step` emission suppression.

Before-step selectors identify a declared executable step and may further match
its subflow path and repetition indexes. Matching enabled faults apply in source
order. Provenance records the fault ID, hook, selected execution address, target,
and operation. These hooks do not provide arbitrary external-system chaos or
network fault injection.

## Expected and unexpected violations

An oracle declares expected constraint and invariant IDs. Applied faults may add
their own expected IDs; duplicates are merged. Evaluation records observed,
expected, unexpected, and missing IDs:

- a missing expected violation always fails the report;
- with strict unexpected behavior, an observed undeclared violation fails;
- without strict unexpected behavior, an extra observed violation is reported
  but does not by itself fail;
- any applied fault with `strict_unexpected: true` makes evaluation strict.

`evaluate_scenario()` returns `OracleEvaluation`, which contains a result when
execution succeeds, a `ReproducibilityManifest`, `OracleReport`, and provenance.
Set `raise_on_mismatch=True` to raise `OracleMismatchError` when the report does
not pass. `OracleEvaluation` and `OracleReport` are supported values from the
`scenario_engine.oracle` submodule; they are not canonical top-level exports.

## Focused complete example

[`examples/oracle_fault.yaml`](../examples/oracle_fault.yaml) starts with balance
10, declares a nonnegative-balance invariant, and calls a payment subflow. An
enabled before-step fault overrides the `debit` write to `-1` and expects the
invariant violation:

```python
from pathlib import Path

from scenario_engine import compile_document, evaluate_scenario, parse_yaml
from scenario_engine.oracle import OracleEvaluation

text = Path("examples/oracle_fault.yaml").read_text(encoding="utf-8")
scenario = compile_document(parse_yaml(text))
evaluation = evaluate_scenario(scenario, root_seed="oracle-guide")

assert isinstance(evaluation, OracleEvaluation)
assert evaluation.result is None
assert evaluation.report.passed is True
assert evaluation.report.observed_invariant_violations == ("balance_nonnegative",)
assert evaluation.report.applied_fault_ids == ("force_overdraft",)
assert any(record.kind == "fault_application" for record in evaluation.provenance.records)
```

The failed debit never commits, so there is no partial state/history/artifact
from it. The oracle nevertheless supplies deterministic evidence that the
intended violation was observed at the selected engine execution point.

See the [DSL reference](dsl-reference.md) for declaration schemas and
[determinism](determinism.md) for the atomic sequence.
