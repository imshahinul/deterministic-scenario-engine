# Deterministic Scenario Engine 3.0.1

DSE 3.0.1 is a compatibility-preserving patch release. The distribution version
advances from 3.0.0 to 3.0.1; Engine 1/Manifest 1 remains 1.0.0 and Engine
2/Manifest 2 remains 2.0.0. DSL, schema, canonical serialization, CLI grammar,
and public Python API contracts are unchanged.

## Changes since 3.0.0

- Clarifies Engine 2 replay help, including the required Schedule/1 input.
- Makes missing-schedule human diagnostics actionable while preserving the
  machine-readable error contract.
- Includes safe, allowlisted failing-field identifiers in relevant diagnostics
  without exposing arbitrary input values.
- Improves installed-distribution identity onboarding so users can verify both
  package metadata and the module path imported by the active interpreter.
- Clarifies the distinction between distribution, engine, and manifest versions.
- Extends regression and release-maintenance coverage, including permanent
  verification of authentic historical release tags.

The earlier TRACK-A4 repair aligned a maintainer's local editable environment;
it is not a shipped runtime feature of this release.

## Compatibility and upgrade guidance

Python 3.11, 3.12, 3.13, and 3.14 remain declared as supported. The runtime
dependency remains `PyYAML==6.0.3`. Upgrade the distribution through the same
Python interpreter used to run DSE, then verify `importlib.metadata.version` and
`scenario_engine.__file__` as shown in the quickstart. Existing Engine 1 and
Engine 2 evidence retains its established compatibility and fail-closed replay
checks.

## Known limits

Engine 2 suite orchestration, cross-major promotion, remote URI input, implicit
schedule-seed derivation, distributed execution, and evidence federation remain
unsupported. This patch does not introduce new engine algorithms, performance
claims, scientific benchmarks, or security certification.
