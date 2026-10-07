# Phase 4.0 Authoring, Diagnostics & Understanding Architecture Freeze

## 1. Phase thesis

Phase 4 asks a conditional design question:

> If qualifying external evidence later authorizes implementation, how should
> Deterministic Scenario Engine (DSE) let a developer author, understand,
> compare, replay, and debug scenarios through stable public surfaces without
> weakening deterministic runtime semantics?

This document is an architecture freeze, not an implementation plan or evidence
of product demand. Every prospective Phase 4 surface is classified as a
`CONDITIONAL_CANDIDATE_SURFACE` unless a later external Product Evidence Gate
packet independently classifies it `SUPPORTED_BY_EVIDENCE`.

The following terms are deliberately distinct:

- `FROZEN_ARCHITECTURE_CONTRACT`: a bounded prospective design that constrains
  any later authorized implementation.
- `VALIDATED_PRODUCT_REQUIREMENT`: a capability backed by qualifying external
  evidence and admitted to implementation scope through the Product Evidence
  Gate.

Freezing the former does not create the latter. This freeze authorizes no code,
API, CLI, schema, dependency, version, release, or runtime change and does not
authorize Phase 4.1.

```text
PHASE4_ARCHITECTURE_FROZEN=YES
PHASE4_IMPLEMENTATION_AUTHORIZED=NO
PHASE4_1_AUTHORIZED=NO
```

## 2. Evidence and governance status

The governing policy is `docs/product-evidence-gate.md`. It permits prospective,
conditional architecture while evidence is insufficient and reserves
implementation MUST/SHOULD scope for externally supported capabilities.

Current governance is:

```text
PHASE4_ARCHITECTURE_FREEZE_AUTHORIZED=YES
CURRENT_PHASE4_EVIDENCE_STATE=INSUFFICIENT
PHASE4_IMPLEMENTATION_AUTHORIZED=NO
PHASE4_1_AUTHORIZED=NO
```

H1 (run-to-replay asymmetry), H2 (filesystem/trust-boundary communication
friction), and H3 (generic DSL/schema diagnostics) remain
`UNVALIDATED_HYPOTHESES`. GitHub Issue #1 is maintenance evidence only. Neither
those hypotheses nor internal architectural preference establish product demand.

## 3. Conditional candidate scope

The complete Phase 4 architectural candidate boundary is:

- run-to-replay coherence and replay-output UX;
- replay compatibility diagnostics;
- filesystem trust-boundary ergonomics;
- actionable deterministic diagnostics and a machine-readable error envelope;
- optional author-time scenario scaffolding;
- scenario-definition structural diff;
- conservative impact/change-amplification analysis;
- a static offline trace viewer;
- canonical consumer workflows and help;
- cross-version replay/inspection fixtures; and
- outside-in consumer validation.

Every item is a `CONDITIONAL_CANDIDATE_SURFACE`, not a validated requirement.
A later evidence packet may admit one bounded problem cluster without admitting
the others. Unsupported candidates remain deferred even though their
architecture is frozen here.

## 4. Non-goals

Phase 4 does not include concurrency or race semantics, actor/lane execution,
schedule generation or exploration, engine v2, distributed execution, worker
orchestration, an adapter SDK, a plugin marketplace, network evidence services,
a hosted dashboard, a general UI product, runtime LLM calls, autonomous scenario
execution, or a large Domain Pack expansion.

It also does not reinterpret existing scenario execution, replay, migration,
inspection, evidence, diff, security, or deterministic canonicalization
contracts. Reserved syntax and presentation space confer no execution semantics.

## 5. Frozen existing contracts

The immutable entry baseline is distribution `deterministic-scenario-engine`
2.1.2 at commit `5128847cd143dd8ee12c89340a75c2d7176fdc6e`, tree
`c96835b7b9b6358066642178d296fe2d4ca5248d`.

```text
ENGINE_VERSION=1.0.0
MANIFEST_ENGINE_VERSION=1.0.0
DSL_VERSION=1
ROOT_EXPORTS=33
CLI_COMMANDS=12
MIGRATION_ROUTES=6
PHASE4_ENGINE_SEMANTIC_CHANGE_ALLOWED=NO
PHASE4_DSL_MAJOR_CHANGE_ALLOWED=NO
```

The twelve CLI commands remain `validate`, `run`, `replay`, `hash`, `inspect`,
`explain`, `diff`, `matrix`, `batch`, `export`, `verify`, and `migrate`. The six
lossless migration routes, exact replay compatibility checks, root exports,
fail-closed readers, and Phase 1-3 public contracts remain unchanged. This
document creates no thirteenth command and no production schema.

## 6. Semantic-address contract

### 6.1 Identity and independence

`scenario.semantic-address/1` is a new, independently versioned candidate
contract for durable references to semantic scenario components. It is not a
YAML/JSON path, JSON Pointer, source location, execution address, list offset, or
filesystem path. Parsing or serializing a scenario differently cannot change a
semantic address when the same semantic identifiers and relationships remain.

```text
SEMANTIC_ADDRESS_CONTRACT=scenario.semantic-address/1
SEMANTIC_ADDRESS_CONTRACT_FROZEN=YES
SEMANTIC_ADDRESS_IS_YAML_PATH=NO
FUTURE_ACTOR_NAMESPACE_RESERVED=YES
```

### 6.2 Grammar

The canonical root namespace is the literal `scenario:` followed by an absolute
component sequence:

```abnf
semantic-address = "scenario:/" component *("/" component)
component        = kind "/" identifier
kind             = "step" / "fault" / "invariant" / "oracle" /
                   "generator" / "derive" / "write" / "emit" /
                   "transition" / "resource" / "constraint" /
                   "actor" / extension-kind
identifier       = 1*(unreserved / pct-encoded)
unreserved       = ALPHA / DIGIT / "-" / "." / "_" / "~"
pct-encoded      = "%" HEXDIG HEXDIG
extension-kind   = "x-" 1*(lower / DIGIT / "-")
```

The grammar is structural: each component is exactly a kind/identifier pair.
Examples are:

```text
scenario:/step/checkout
scenario:/step/checkout/fault/decline
scenario:/invariant/inventory_nonnegative
scenario:/actor/customer_a/step/read_inventory
```

`actor` is reserved solely for future actor scope. Phase 4 cannot construct,
interpret, schedule, compare, execute, or otherwise assign actor/lane semantics.
`lane` is likewise reserved as a future standard kind but is not accepted by a
Phase 4 producer; a future independently reviewed revision may activate it.

### 6.3 Canonical serialization and normalization

- The scheme and standard kinds are lowercase ASCII exactly as shown.
- Identifiers are Unicode NFC before UTF-8 percent encoding.
- Unreserved characters are emitted literally. Every other UTF-8 byte is
  percent-encoded using uppercase hexadecimal. `/`, `%`, control characters,
  spaces, and non-ASCII bytes are therefore escaped.
- Empty identifiers, `.`, `..`, empty components, a trailing slash, malformed
  UTF-8, malformed escapes, overlong UTF-8, and encoded unreserved characters
  are non-canonical and rejected.
- Decoding followed by NFC normalization and canonical re-encoding defines the
  sole canonical serialization. Producers emit only canonical addresses;
  readers reject rather than silently repair non-canonical durable input.
- Equality is byte equality of canonical UTF-8 serialization. Ordering, when a
  contract needs it, is unsigned lexicographic ordering of those bytes. Prefix
  comparison occurs only on complete kind/identifier pairs.

### 6.4 Indexes, extensions, and bounds

Stable semantic identifiers are preferred over positional indexes. Numeric text
is an ordinary identifier only when it is the declared stable semantic ID; no
address may infer an array index. If a future schema truly requires positional
identity, it requires a separately frozen standard kind and cannot overload
`step/0` or another existing form.

Unknown bare kinds fail closed. Extension kinds use the `x-` prefix, remain
opaque, convey no core execution authority, and compare only by canonical bytes.
Consumers may preserve a syntactically valid extension address but cannot infer
behavior from it. Standard-kind additions require a reviewed contract revision;
extensions cannot redefine standard kinds.

Maximum depth is 32 kind/identifier pairs. Maximum canonical serialized length
is 2,048 UTF-8 bytes. Implementations may use lower operation-specific limits
only when explicitly versioned and reported; they may not silently truncate.

## 7. Replay contract design

This section freezes `CONDITIONAL_CANDIDATE_SURFACE` architecture only. A run
artifact is suitable for supported replay only when it records or securely
references the complete already-required compatibility tuple and replay inputs:
scenario identity and canonical hash, engine and DSL versions, RNG/ID/generator
and plugin coordinates, seed, reference clock, explicit inputs/resources,
suite/case coordinates where applicable, and all other coordinates required by
the frozen replay API. A result alone is not automatically replay input.

Capabilities remain independent:

- **inspectable:** bounded non-executing readers can validate and expose recorded
  evidence without inventing unavailable facts;
- **replayable:** all exact compatibility and source/input requirements for the
  existing replay operation are satisfied;
- **migratable:** a known, provably lossless route can create a new artifact
  while preserving source bytes and provenance;
- **incompatible:** a required coordinate is absent, unsupported, or mismatched,
  or replay data is incomplete.

Inspectable does not imply replayable. Migratable does not imply replayable.
Migration availability does not weaken the requirement to replay only a fully
compatible target. Incompatibility fails closed.

A dedicated replay-output UX is architecturally warranted as a conditional
renderer over the existing replay operation because it can clearly separate
compatibility assessment, attempted execution, deterministic comparison, and
next action. It is not a new replay engine, does not mutate source evidence, and
does not change replay success criteria.

## 8. Diagnostic and error model

### 8.1 Replay reason taxonomy

The candidate stable replay reason vocabulary is:

```text
ENGINE_VERSION_UNSUPPORTED
MANIFEST_VERSION_UNSUPPORTED
SCENARIO_MISMATCH
REPLAY_DATA_INCOMPLETE
MIGRATION_AVAILABLE
MIGRATION_UNAVAILABLE
```

The compatibility domain owns these codes and their deterministic mapping from
existing checks; CLI and human renderers do not reinterpret failures. Machine
rendering is canonical for its independently versioned envelope. Human rendering
is derived presentation.

Each reason has one stable next-action semantic: use a supported engine, use a
supported manifest reader/migration, supply the exact scenario, supply named
missing replay coordinates, execute an explicit reviewed migration, or retain/
inspect the source without replay. A next action never promises success, invokes
migration automatically, downloads software, or bypasses a failed check.

### 8.2 Human diagnostic structure

Candidate diagnostics have these semantic fields:

```text
code
category
exit_code
semantic_path
message
expected
received
remediation
details
```

Stable contract consists of codes, categories, schema, exit-code mapping, and
required semantic fields. Exact prose, layout, punctuation, color, wrapping,
and localization are presentation and are not stable machine interfaces.
`semantic_path`, when present, is a canonical `scenario.semantic-address/1`, not
a YAML path. `expected`, `received`, and `details` are bounded typed values and
may be absent when disclosure would be unsafe or the value is unavailable.

Codes and categories are finite and domain-owned. Ordering is deterministic:
source semantic address, then category/code, then a domain-defined stable
ordinal. Diagnostics contain no wall-clock time, random IDs, host-specific paths,
unordered exception text, secrets, credentials, environment values, or raw
provider payloads. Redaction occurs before both machine and human rendering.

### 8.3 Machine-readable envelope

`scenario.error/1` is the minimal independently versioned candidate envelope for
CLI automation without prose parsing:

```text
schema: "scenario.error/1"
code: stable finite string
category: stable finite string
exit_code: integer from the existing CLI exit contract
semantic_path: canonical address or null
message: bounded human presentation string
expected: optional bounded typed value
received: optional bounded typed value
remediation: optional bounded stable action identifier
details: optional bounded canonical object
```

The envelope represents one primary error. Multiple errors, localization,
causal stacks, arbitrary metadata, traceback transport, and warning streams are
outside v1. Canonical machine rendering is compact UTF-8 JSON with sorted object
keys and LF at the CLI boundary. Unknown schema versions and unknown required
codes fail closed. The schema is not coupled to package, engine, manifest, DSL,
semantic-address, or evidence-bundle versions.

Phase 4.5 implements this envelope on the established stderr error channel when
the existing global `--json` mode is selected. Required fields are `schema`,
`code`, `category`, `exit_code`, and `message`. The optional fields
`semantic_path`, `expected`, `received`, `remediation`, and `details` are omitted
when unavailable; explicit null and empty objects are not emitted. Exact message
prose is presentation, not the primary automation contract.

The finite categories exposed by this checkpoint are `DSL_SCHEMA`,
`DSL_SEMANTIC`, `REPLAY_COMPATIBILITY`, `FILESYSTEM_TRUST_BOUNDARY`, `CLI_USAGE`,
`COMMAND`, and `INTERNAL`. The domain codes are the three DSL codes, the six
replay compatibility codes, and the nine filesystem trust-boundary codes frozen
in their respective sections; bounded fallback codes are `CLI_ERROR`,
`COMMAND_ERROR`, and `INTERNAL_ERROR`. Human and JSON renderers consume the same
internal canonical diagnostic. Details are sorted, scalar-only, bounded, and
never contain exception dumps, tracebacks, stack locals, or arbitrary payloads.

## 9. Filesystem trust-boundary UX

The current local-only, explicit-root, regular-file, no-follow, bounded,
fail-closed behavior is preserved. Conditional diagnostics may explain:

- a relative path where an absolute path is required;
- a URI or remote path where only a local path is permitted;
- a resolved path outside the explicit allowed root;
- a missing local artifact; or
- an invalid, existing, aliased, or otherwise unsafe destination.

Explanations disclose only normalized safe context and stable reason codes. They
do not echo credentials, URL query strings, arbitrary file contents, or more host
path detail than the caller supplied. No convenience fallback searches the
working directory, follows a symlink, expands environment variables, retrieves a
URI, overwrites output, or broadens an allowed root.

```text
FILESYSTEM_TRUST_BOUNDARY_PRESERVED=YES
```

## 10. Author-time scaffolding boundary

The optional conditional architecture is a one-way authoring pipeline:

```text
intent/prose
→ optional authoring provider
→ proposed DSL
→ ordinary DSE validation
→ human review/freeze
→ ordinary deterministic runtime
```

The provider is explicit, provider-neutral, replaceable, and outside runtime. A
fully deterministic template provider is possible. Provider output is untrusted
proposed text: it cannot register code, execute scenarios, select plugins, relax
validation, mark itself reviewed, or enter a reproducibility manifest as runtime
authority. Core runtime has no provider dependency and frozen DSL validation is
always applied before a human explicitly accepts source.

```text
RUNTIME_LLM_CALLS=NO
SCAFFOLD_PROVIDER_RUNTIME_AUTHORITY=NONE
GENERATED_DSL_BYPASSES_VALIDATION=NO
PROVIDER_REQUIRED_FOR_CORE_RUNTIME=NO
```

Provider prompts, responses, credentials, network behavior, cost, availability,
and nondeterminism are authoring observations, not DSE runtime semantics.
Autonomous correction/execution and implicit network providers are excluded.

Phase 4.6 realizes this boundary as `scenario.scaffold/1`. Its default
`deterministic-template` provider accepts only bounded scenario/step identifiers
and an explicit clock, emits byte-stable DSL 1, and performs no network or model
calls. The orchestration layer—not the provider—passes every proposal through the
ordinary DSL parser/compiler. `scenario scaffold` writes the proposed draft to
stdout and never invokes runtime execution; provider identity/version appear only
as non-runtime JSON authoring metadata. Failures use category
`SCAFFOLD_AUTHORING` and codes `SCAFFOLD_REQUEST_INVALID`,
`SCAFFOLD_PROVIDER_NOT_FOUND`, `SCAFFOLD_PROVIDER_FAILED`, or
`SCAFFOLD_OUTPUT_INVALID` through `scenario.error/1` in JSON mode.

## 11. Scenario-definition structural diff

This conditional candidate is a semantic definition diff, not textual YAML diff
and not the existing evidence/result diff reinterpreted. Both inputs are safely
parsed and validated under their declared DSL contract; comments, key order,
formatting, aliases, and serialization layout are not semantic changes.

The candidate finite categories are step added/removed/changed, generator
changed, derive expression changed, write target changed, emit changed,
transition changed, fault changed, invariant changed, oracle changed, and
resource/constraint changed. Every durable reference is a canonical
`scenario.semantic-address/1`. Records are ordered by canonical address then
category and stable field key. Values use existing safe canonical typed-value
rules and explicit unavailable/truncated markers.

The independently versioned durable report candidate is
`scenario.definition-diff/1`. It records input identities and hashes, DSL
versions, ordered typed changes, completeness/truncation, and configured bounds.
It does not claim behavioral equivalence, runtime impact, replay compatibility,
or source-location stability.

## 12. Impact and change-amplification model

Impact analysis is a conservative static conditional candidate over validated
definitions. Its only classifications are:

```text
DIRECT
TRANSITIVE_POSSIBLE
UNKNOWN
```

`UNKNOWN != UNAFFECTED`. There is intentionally no `UNAFFECTED` conclusion in
v1, and the report never claims behavioral equivalence.

The dependency graph has canonical semantic addresses as nodes. Directed edges
represent explicit static may-depend-on relationships: referenced reads/writes,
derives, generators, transitions, faults, invariants, oracles, resources, and
constraints. `A → B` means a definition change at A may affect B under the
declared static relation. A changed node is `DIRECT`; a node reachable through
known edges is `TRANSITIVE_POSSIBLE`; anything whose dependency cannot be fully
resolved within language knowledge or limits is `UNKNOWN`. Dynamic/opaque
extensions create unknown frontiers rather than negative conclusions.

Cycles are collapsed into deterministic strongly connected components. Any
component containing or reachable from a direct change is conservatively
`TRANSITIVE_POSSIBLE` except direct members, which remain `DIRECT`. Truncation,
unsupported expressions, unknown extensions, missing declarations, or exceeded
bounds propagate `UNKNOWN` with a stable reason.

Amplification is reported as the rational pair:

```text
numerator = count of distinct addressable nodes classified DIRECT,
            TRANSITIVE_POSSIBLE, or UNKNOWN
denominator = count of distinct addressable nodes in the bounded analyzed graph
```

Both integers and the reduced fraction are recorded; floating-point output is
not authoritative. Provable results are direct syntax facts and reachability over
a complete known graph. Inferred results are may-depend reachability and are
labelled accordingly. The independently versioned report candidate is
`scenario.impact/1` and records graph/rule version, limits, completeness, input
hashes, classifications, rational amplification, and stable reasons.

Default architectural ceilings are 100,000 nodes, 500,000 edges, graph depth
256, and 16 MiB canonical report bytes. Exceeding a ceiling produces bounded
partial/unknown output or a bound error according to the eventual explicit API;
it never silently drops nodes or reports unaffected.

```text
IMPACT_ANALYSIS_CONSERVATIVE=YES
```

## 13. Static trace viewer

The conditional architecture is:

```text
local evidence/result
→ bounded deterministic static renderer
→ one self-contained HTML file
```

The viewer represents scenario identity, step timeline, before/after state,
faults, invariants and oracles, emitted artifacts, provenance, hashes, and
versions. Missing evidence is shown as unavailable and never reconstructed. A
reserved empty presentation region may host future actor/lane traces, but Phase
4 defines no actor/lane data model, grouping, ordering, or execution semantics.

The independently versioned renderer contract candidate is
`scenario.trace-view/1`; it identifies the normalized input schema/hash,
renderer contract, completeness, redaction policy, and deterministic sections.
The HTML uses embedded CSS and escaped data, no scripts by default, no external
assets, active forms, remote fonts, links that fetch resources, telemetry,
cookies, storage, or source mutation. Content Security Policy metadata denies all
network sources. Rendering never executes evidence or named code.

Architectural ceilings are 256 MiB aggregate validated input, 100,000 timeline
events, depth 64, 1 MiB per displayed value before deterministic truncation, and
512 MiB output. The renderer reports truncation and fails before partial
publication when the output ceiling cannot be met. Output is atomically written
to an explicit absent local destination.

```text
NETWORK_REQUIRED=NO
SERVER_REQUIRED=NO
TELEMETRY=NO
EVIDENCE_MUTATION=NO
```

## 14. Consumer journey contract

Candidate canonical journeys are:

```text
CJ-01 validate valid scenario
CJ-02 validate malformed DSL
CJ-03 run deterministic scenario
CJ-04 run → replay
CJ-05 relative evidence path failure
CJ-06 inspect/explain
CJ-07 export → verify
CJ-08 scenario-definition diff
CJ-09 static trace viewer
CJ-10 scaffold → validate
```

Future implementation baseline records capture exact input/command, exit code,
stdout, stderr, artifacts, and observable friction. Secrets and uncontrolled host
state are excluded or redacted. Existing journeys establish behavior before a
public-surface change; the same records are captured after it.

Canonical workflow families are install → validate → run → replay; inspect →
explain; scenario A → definition diff → impact report; evidence export → verify;
evidence → static trace viewer; and intent → scaffold → validate → human freeze.
Help remains a renderer of accepted public contracts, not an alternate contract.

If and only if the evidence gate later authorizes implementation, every Phase 4
public checkpoint is governed by:

```text
EVERY_PHASE4_PUBLIC_CHECKPOINT_REQUIRES =
existing applicable consumer journeys remain passing
+
a new black-box journey for the new public surface
```

## 15. Cross-version compatibility policy

Readability, inspectability, diffability, replayability, and migratability remain
separate reported capabilities. Unknown artifact/schema versions fail closed.
Replay requires the complete exact frozen compatibility tuple; no Phase 4
diagnostic or presentation layer weakens it. Cross-version fixtures are immutable
bytes plus expected non-executing compatibility/inspection results and, only
where already supported, replay results. They do not create support for an
otherwise unsupported version.

Every durable candidate artifact has an independent version:

| Candidate artifact | Independent contract |
|---|---|
| Semantic address | `scenario.semantic-address/1` |
| Machine error | `scenario.error/1` |
| Definition diff | `scenario.definition-diff/1` |
| Impact report | `scenario.impact/1` |
| Static trace view metadata | `scenario.trace-view/1` |

Those versions do not derive from distribution, engine, manifest, DSL, bundle,
or each other. A contract revision is required when accepted meaning cannot be
represented compatibly. Migration is explicit, loss-aware, non-destructive, and
separately versioned; reading never silently upgrades.

## 16. Security and resource bounds

All prospective inputs are untrusted data unless an existing contract explicitly
classifies caller-supplied Python as trusted and unsandboxed. Safe parsing,
canonical encoding, bounded depth/count/bytes, no-follow filesystem handling,
explicit roots, absent destinations, atomic publication, deterministic ordering,
and fail-closed unknown versions remain mandatory architectural constraints on
any later authorized candidate.

Diagnostics and renderers are secret-safe: no traceback, arbitrary exception
text, credentials, environment, host identity, absolute path beyond necessary
caller context, or provider payload enters durable output. HTML escapes all
content and has no network authority. Scaffolding output receives no execution
authority. Structural analysis never executes expressions, generators, plugins,
providers, scenarios, assertions, migrations, or artifacts.

The semantic address, impact, and viewer limits are frozen above. Candidate
diagnostics additionally cap one canonical `scenario.error/1` at 1 MiB, depth 32,
and 1,000 detail entries; human presentation may be smaller but must disclose
truncation deterministically. Later implementation may choose stricter defaults
only through an explicit public contract and cannot raise hard ceilings without
security review.

## 17. Cross-phase compatibility

- **Phase 4:** authoring, understanding, diagnostics, and local static
  presentation only.
- **Phase 5:** deterministic logical concurrency, if independently authorized.
- **Phase 5X:** optional schedule-exploration research, separately governed.
- **Phase 6:** embedding, integration, and extensibility.
- **Phase 7:** distributed execution and evidence federation.

Phase 4 implements none of the later phases. Semantic addresses reserve future
actor/lane-compatible namespace shape without defining actors, lanes, schedules,
workers, federation, or ordering. Opaque extension and independent version rules
allow later additive design without making future semantics valid in Phase 4.
No current Phase 1-3 artifact is retroactively assigned a semantic address.

## 18. Future checkpoint sequence

The candidate order, conditional on later evidence-gate authorization at each
applicable boundary, is:

```text
4.1  run → replay workflow
4.2  replay compatibility diagnostics
4.3  filesystem trust-boundary ergonomics
4.4  actionable human diagnostics
4.5  machine-readable error envelope
4.6  author-time scaffolding
4.7  scenario-definition structural diff
4.8  conservative impact/change-amplification
4.9  static trace viewer
4.10 canonical workflow/help
4.11 cross-version replay/inspection fixtures
4.12 hardening
4.13 independent consumer acceptance
4.14 release candidate/publication
```

This ordering grants zero implementation authorization. It neither promises that
all checkpoints will occur nor allows evidence for one problem cluster to admit
unrelated candidates.

## 19. External evidence gate

Before Phase 4.1 may begin, at least one externally grounded Phase-4-relevant
problem cluster must represent a real user/workflow problem, fall within DSE
responsibility, not merely be a maintenance defect, not be vanity/adoption
telemetry, not be internal architectural preference alone, not rely only on
uncorroborated hypotheses, and not already be solvable by a trivial documentation
correction.

The evidence packet and classifications in `docs/product-evidence-gate.md` are
required. Only `SUPPORTED_BY_EVIDENCE` capabilities may enter implementation
MUST/SHOULD scope. Architecture review, this document, H1-H3, and maintenance-only
Issue #1 cannot satisfy the gate.

```text
PHASE4_EXTERNAL_EVIDENCE_GATE_FROZEN=YES
CURRENT_PHASE4_EVIDENCE_STATE=INSUFFICIENT
PHASE4_IMPLEMENTATION_AUTHORIZED=NO
PHASE4_1_AUTHORIZED=NO
```

## 20. Pre-implementation baseline rule

No Phase 4 implementation baseline is created now. After external evidence and
an explicit implementation authorization, the first applicable checkpoint must
capture the relevant CJ-01 through CJ-10 black-box records against the then-
immutable pre-change commit before product code changes. Every applicable
existing journey must remain passing and every new public surface gets a new
outside-in journey. Unit tests or internal API tests cannot substitute for this
consumer baseline.

## 21. Decision register

| Decision | Frozen resolution | Status |
|---|---|---|
| Architecture versus demand | A frozen conditional design is not a validated product requirement | Accepted |
| Semantic addressing and future actor namespaces | Use independent `scenario.semantic-address/1`, never raw serialization paths; reserve actor and future lane shape without semantics | Accepted |
| Runtime semantics | Keep engine 1.0.0, manifest engine 1.0.0, and DSL 1 unchanged | Accepted |
| Replay posture | Preserve exact checks; inspectable, replayable, migratable, and incompatible remain distinct | Accepted |
| Diagnostics | Stable semantic codes/schema; prose is presentation; deterministic and secret-safe | Accepted |
| Machine errors | Minimal independent `scenario.error/1`; no prose parsing | Accepted |
| Filesystem ergonomics | Improve explanation only; preserve fail-closed trust boundary | Accepted |
| Scaffolding | Optional author-time provider with no runtime authority; validation and human freeze required | Accepted |
| Definition comparison | Semantic structural diff with canonical addresses, not textual YAML diff | Accepted |
| Impact | Conservative may-impact model; `UNKNOWN != UNAFFECTED`; no equivalence claim | Accepted |
| Viewer | One deterministic self-contained offline HTML file; no network/server/telemetry/mutation | Accepted |
| Consumer acceptance | Existing journeys plus one new black-box journey per authorized public checkpoint | Accepted, conditionally operative |
| Versioning | Independently version every durable candidate contract | Accepted |
| Implementation | Evidence gate remains closed; observation hold follows this freeze | Accepted |

## 22. Risks

- Semantic identifiers may be absent or unstable in some current definitions;
  positional fallback is prohibited, so a later evidence-backed design may need
  an additive authoring constraint without changing DSL 1 meaning.
- A diagnostic taxonomy can accidentally expose internal structure or secrets;
  finite domain ownership, redaction, and bounded typed fields mitigate this.
- Replay UX can imply compatibility where none exists; explicit capability
  separation and fail-closed reason ownership mitigate this.
- Scaffolding can be mistaken for trusted generation; mandatory ordinary
  validation and human freeze preserve authority boundaries.
- Static dependency analysis can be overclaimed; the three conservative classes,
  unknown propagation, and absence of an unaffected verdict limit that risk.
- Self-contained HTML can become an injection or resource-exhaustion surface;
  escaping, CSP, no scripts/network, validation, and hard limits are required.
- Reserved actor/lane forms could be misconstrued as Phase 5 semantics; the
  reservation is syntax-space stewardship only and is unusable for execution.
- Freezing broad candidates could be read as demand; repeated conditional labels
  and the closed external evidence gate are normative safeguards.

## 23. Phase 4 exit criteria

Phase 4 as a product phase cannot exit until separately authorized future work
has qualifying evidence, accepted checkpoint artifacts, preserved Phase 1-3
contracts, consumer acceptance, security/hardening evidence, and an explicitly
authorized release decision. This Phase 4.0 architecture checkpoint exits when:

- exactly one architecture document freezes all named candidate boundaries;
- every unsupported surface is explicitly conditional;
- H1-H3 remain unvalidated and the Product Evidence Gate remains closed;
- engine, manifest-engine, DSL, exports, CLI, migrations, and runtime behavior
  are unchanged;
- semantic addressing is serialization-independent and actor namespace is only
  reserved;
- replay, diagnostics, filesystem, scaffolding, diff, impact, viewer, consumer,
  versioning, security, and cross-phase boundaries are internally coherent;
- targeted documentation validation and `git diff --check` pass; and
- one candidate documentation-only commit and one external audit artifact record
  immutable acceptance.

## 24. Final frozen disposition

```text
PHASE4_SCOPE_FROZEN=YES
PHASE4_SCOPE_CLASSIFICATION=CONDITIONAL_CANDIDATE_SURFACES
PHASE4_ENGINE_SEMANTIC_CHANGE_ALLOWED=NO
PHASE4_DSL_MAJOR_CHANGE_ALLOWED=NO
SEMANTIC_ADDRESS_CONTRACT=scenario.semantic-address/1
SEMANTIC_ADDRESS_CONTRACT_FROZEN=YES
SEMANTIC_ADDRESS_IS_YAML_PATH=NO
FUTURE_ACTOR_NAMESPACE_RESERVED=YES
REPLAY_CONTRACT_FROZEN=YES
DIAGNOSTIC_CONTRACT_FROZEN=YES
ERROR_ENVELOPE_CONTRACT_FROZEN=YES
FILESYSTEM_TRUST_BOUNDARY_PRESERVED=YES
SCAFFOLD_PROVIDER_RUNTIME_AUTHORITY=NONE
RUNTIME_LLM_CALLS=NO
GENERATED_DSL_BYPASSES_VALIDATION=NO
PROVIDER_REQUIRED_FOR_CORE_RUNTIME=NO
SCENARIO_DIFF_CONTRACT_FROZEN=YES
IMPACT_ANALYSIS_CONSERVATIVE=YES
TRACE_VIEWER_NETWORK_REQUIRED=NO
TRACE_VIEWER_SERVER_REQUIRED=NO
TELEMETRY=NO
EVIDENCE_MUTATION=NO
CONSUMER_JOURNEY_POLICY_FROZEN=YES
CROSS_VERSION_COMPATIBILITY_POLICY_FROZEN=YES
HYPOTHESES_REMAIN_UNVALIDATED=YES
UNSUPPORTED_SURFACES_CLASSIFIED_AS_CANDIDATES=YES
PHASE4_EXTERNAL_EVIDENCE_GATE_FROZEN=YES
CURRENT_PHASE4_EVIDENCE_STATE=INSUFFICIENT
PHASE4_IMPLEMENTATION_AUTHORIZED=NO
PHASE4_1_AUTHORIZED=NO
PHASE4_ARCHITECTURE_FROZEN=YES
NEXT_ACTIVITY=OBSERVATION_HOLD
```

This is a successful architecture freeze and an intentional implementation hold.

## 25. Phase 4.1 owner-authorization amendment

The evidence and authorization statements above record the historical Phase 4.0
decision and remain unchanged: the external evidence state was `INSUFFICIENT` and
was not reclassified. For the Phase 4.1 development track only, the project owner
subsequently supplied an explicit authorization that supersedes the prior
implementation hold without asserting that the external evidence gate passed:

```text
PHASE4_IMPLEMENTATION_AUTHORIZATION_SOURCE=PROJECT_OWNER_OVERRIDE
PHASE4_EXTERNAL_EVIDENCE_REEVALUATED=NO
PHASE4_1_AUTHORIZED=YES
```
