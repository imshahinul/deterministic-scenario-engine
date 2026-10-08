# Deterministic Scenario Engine 2.2.0

Release 2.2.0 is an additive distribution release. It retains engine
compatibility version 1.0.0, manifest engine version 1.0.0, and DSL version 1.

## Highlights

- First-class `run --replay-out` → `replay` workflows using `suite.run/1`, with
  fail-closed compatibility diagnostics.
- Actionable human diagnostics and the `scenario.error/1` machine-readable
  error envelope, localized with `scenario.semantic-address/1` where available.
- Author-time `scaffold` → `validate` workflow under `scenario.scaffold/1`.
- Validated scenario-definition structural diff (`scenario.definition-diff/1`)
  and separate conservative static impact analysis (`scenario.impact/1`).
- Deterministic, self-contained, offline trace views
  (`scenario.trace-view/1`) with secret redaction and no network, telemetry,
  server, or CDN dependency.
- Installed export of the frozen public compatibility corpus
  (`scenario.compatibility-fixtures/1`) without a source checkout.
- Filesystem trust-boundary diagnostics, packaged-fixture integrity checks,
  reproducible artifact hardening, and secret-safe inspection surfaces.

## Compatibility and migration

Inspection support does not imply replay support. Unknown contracts and version
states fail closed. Migration remains explicit and non-destructive; reading does
not silently migrate an artifact. Current and selected supported historical
fixture behavior is tested, but this release does not claim universal backward
compatibility or unsupported historical replay.

There are no intentional breaking changes to the existing public engine, DSL,
manifest, or execution-diff contracts. Existing deterministic compatibility
identities remain unchanged. The new Phase 4 contracts are additive. Exact
replay still requires the recorded scenario, explicit inputs, and compatible
execution coordinates.

Supported Python versions are 3.11, 3.12, 3.13, and 3.14.

## Scope boundaries

This release does not add runtime LLM integration, actor or lane execution,
concurrency semantics, a hosted or network trace-view service, or automatic
migration. Definition diff and impact analysis do not prove formal behavioral
equivalence.
