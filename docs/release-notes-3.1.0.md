# Deterministic Scenario Engine 3.1.0

The source distribution version is 3.1.0. PyPI and GitHub Releases are
authoritative for actual publication and release history. These notes describe
the distribution contents; they do not authorize tagging or publication.

## Additive features

- Ordered serial Engine 2 suite execution through the module-qualified
  `scenario_engine.engine2_suite` API and accepted
  `scenario.engine2-case/1`, `scenario.engine2-suite-plan/1`, and
  `scenario.engine2-suite/1` contracts.
- Strict canonical suite reading and offline aggregate verification, including
  exact native Result/2, Manifest/2, and Schedule/1 child-byte integrity and
  cross-artifact coordinate linkage.
- Finite explicit schedule-seed sweeps through the module-qualified
  `scenario_engine.engine2_explore` API, preserving supplied seed order and the
  suite's authoritative native evidence.

## Compatibility guarantees

- The distribution coordinate advances from 3.0.1 to 3.1.0 only.
- Engine 1 remains 1.0.0 with DSL 1, Result/1, Manifest/1, and Suite Run/1.
- Engine 2 remains 2.0.0 with DSL 2, Result/2, Manifest/2, and Schedule/1.
- Existing canonical bytes, compatibility fixtures, API export manifests,
  historical release identities, and accepted golden vectors remain unchanged.
- The new suite aggregate is distinct from and does not produce, promote, or
  reinterpret historical Suite Run/2.

## Python support

Python 3.11, 3.12, 3.13, and 3.14 remain supported. Declared dependency and
optional-extra constraints are unchanged.

## Evidence integrity and security limitations

Offline suite verification proves canonical aggregate integrity, exact supplied
child bytes and native identities, and coordinate linkage. It does not prove that
execution occurred and is not exact replay. Exact replay separately requires the
exact scenario, effective inputs, recorded schedule, and trusted plugin registry.
Plugin callables are trusted, unsandboxed Python and are not a security boundary.
Canonical error records are bounded claims and do not independently prove the
originating exception. No network or remote evidence resolver is introduced.

## Explicit non-goals

This distribution does not provide exhaustive state-space exploration,
systematic scheduler branching, race-detection completeness, shrinking or
minimization, parallel or distributed execution, remote URI inputs, hidden plugin
discovery, implicit schedule-seed derivation, cross-major promotion, or automatic
migration. It does not change package-root exports or authorize publication.
