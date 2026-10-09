# Deterministic Scenario Engine 3.0.0

**Status: RELEASED October 9, 2026.** Distribution 3.0.0 is published on
[PyPI](https://pypi.org/project/deterministic-scenario-engine/3.0.0/) and as a
[GitHub Release](https://github.com/imshahinul/deterministic-scenario-engine/releases/tag/3.0.0).

This copy on `main` records the post-release publication state. The original
published 3.0.0 tag retains the historical prepublication release-notes bytes.

## Added

- Engine 2.0.0 execution for integer DSL 2 logical actors.
- Explicit independent unsigned 64-bit schedule seeds.
- Canonical Result/2, Manifest/2, and Schedule/1 with exact replay and tamper
  detection.
- Actor-aware inspect/explain and deterministic self-contained offline trace
  viewing.
- Public module-qualified Engine 2 APIs and installed compatibility fixture
  pack `/2` alongside preserved fixture pack `/1`.

## Preserved

DSL 1 and Engine 1.0.0 parsing, execution, Result/1, Manifest/1, Suite Run/1,
replay, package-root Python APIs, CLI defaults, RNG/ID algorithms, Phase 4
contracts, and immutable golden vectors remain byte-compatible.

## Compatibility and security

Only DSL 1/Engine 1 and DSL 2/Engine 2 execute. Cross-major, unknown, mixed, and
incomplete coordinates fail closed without silent migration or package-version
inference. Actor, history, scheduler, nesting, input, schedule-byte, and
result-byte ceilings are enforced. Duplicate JSON keys, invalid seeds,
noncanonical addresses, remote URIs, no-follow filesystem violations, replay
tampering, and secret reflection are rejected or redacted.

## Support and known limits

Python 3.11, 3.12, 3.13, and 3.14 are supported. Suite Run/2 is strict
schema/reader support only; Engine 2 suite orchestration is not implemented.
No network-backed source discovery, implicit seed derivation, or cross-major
promotion is supported.

## Publication verification

The published release uses the exact retained reproducible wheel and sdist.
Their production PyPI and GitHub Release SHA256 digests match the qualification
evidence. Release verification installed the published artifacts outside the
source tree on every supported Python, reran DSL 1 and DSL 2 run/replay and
hostile-input smokes, and inspected rendered metadata and links.
