# Canonical installed-package workflows

This is the canonical DSE user workflow document. Every ordinary command below
uses the installed package and portable files created here; no source checkout,
repository example, network service, API key, or maintainer-local path is needed.
The global `--json` option precedes the command.

The examples set `DSE_DEMO` to the physical absolute path of a temporary
directory. Resolving the physical path avoids operating-system aliases (for
example, a symlinked temporary-directory prefix) at filesystem trust boundaries.

## Install and create a scenario

```console
python3 -m pip install deterministic-scenario-engine
export DSE_DEMO="$(cd "${TMPDIR:-/tmp}" && pwd -P)/dse-demo"
rm -rf "$DSE_DEMO"
mkdir -p "$DSE_DEMO"
cat > "$DSE_DEMO/scenario.yaml" <<'YAML'
dsl_version: 1
scenario: dse_demo
clock: {start: '2026-01-01T00:00:00Z'}
initial_state: {count: 0}
steps:
  - id: increment
    write: {count: {$literal: 1}}
    emit:
      - type: count_changed
        fields: {count: {$state: count}}
    transition: null
YAML
cp "$DSE_DEMO/scenario.yaml" "$DSE_DEMO/scenario-before.yaml"
sed 's/{$literal: 1}/{$literal: 2}/' "$DSE_DEMO/scenario.yaml" > "$DSE_DEMO/scenario-after.yaml"
scenario --help
```

Installing a checkout with `python3 -m pip install .` is
**source-development-only**. Installed-package workflows are primary.

## Validate

```console
scenario validate "$DSE_DEMO/scenario.yaml"
```

Validation compiles the definition but does not execute it.

## Run → replay

```console
scenario --json run "$DSE_DEMO/scenario.yaml" --seed demo-seed --run-index 0 --replay-out "$DSE_DEMO/replay.json" > "$DSE_DEMO/result.json"
scenario --json replay "$DSE_DEMO/replay.json" --scenario "$DSE_DEMO/scenario.yaml" > "$DSE_DEMO/replayed-result.json"
cmp "$DSE_DEMO/result.json" "$DSE_DEMO/replayed-result.json"
```

The run's stdout is the normal `scenario.result/1` execution result. It is
inspectable but is **not** automatically replayable. `--replay-out` separately
writes the supported canonical `suite.run/1` replay artifact, and `scenario
replay` consumes that artifact with the exact scenario (and the same `--inputs`
if inputs were used). The destination must be absent.

Incompatible replay fails closed with exit 5. Stable rejection reasons include
`ENGINE_VERSION_UNSUPPORTED`, `MANIFEST_VERSION_UNSUPPORTED`,
`SCENARIO_MISMATCH`, and `REPLAY_DATA_INCOMPLETE`; migration disposition may be
`MIGRATION_AVAILABLE` or `MIGRATION_UNAVAILABLE`. These codes describe rejection
and never weaken compatibility checks or trigger automatic migration.

### DSL 2 logical actors

DSL 2 uses Engine 2 and requires an independent unsigned 64-bit schedule seed.
The generation `--seed` is never reinterpreted or used to derive it. Result/2 is
written to stdout; `--result-out` is optional, while the replay-authoritative
Schedule/1 destination is required and must be an absent absolute local path.

```console
scenario validate "$DSE_DEMO/actors.yaml"
scenario --json run "$DSE_DEMO/actors.yaml" --seed generation-seed --schedule-seed 7 --run-index 0 --schedule-out "$DSE_DEMO/schedule.json" --result-out "$DSE_DEMO/result.json"
scenario --json replay "$DSE_DEMO/result.json" --scenario "$DSE_DEMO/actors.yaml" --schedule "$DSE_DEMO/schedule.json" > "$DSE_DEMO/replayed-result.json"
cmp "$DSE_DEMO/result.json" "$DSE_DEMO/replayed-result.json"
```

Both outputs are constructed before publication. Each destination is published
atomically as an absent file; if this command publishes one output and then the
other publication fails, it removes the output created by this command. This is
safe staging/finalization behavior, not a claim of filesystem-wide atomicity.

## Inspect / explain

```console
scenario --json inspect "$DSE_DEMO/result.json" --kind result > "$DSE_DEMO/inspection.json"
scenario --json explain "$DSE_DEMO/result.json" > "$DSE_DEMO/explanation.json"
```

`inspect` summarizes normalized recorded evidence across its supported artifact
kinds. `explain` is result-specific and presents available step and state-change
evidence. Both are read-only, redact secret-prone values by default, do not
re-execute, and label unavailable evidence rather than inventing it.

## Execution artifact diff

```console
scenario --json run "$DSE_DEMO/scenario-after.yaml" --seed demo-seed > "$DSE_DEMO/result-after.json"
scenario --json diff "$DSE_DEMO/result.json" "$DSE_DEMO/result-after.json" --kind result --mode complete > "$DSE_DEMO/execution-diff.json"
test $? -eq 1
```

`scenario diff` compares recorded execution artifacts. Exit 0 means equal; a
valid unequal comparison exits 1.

## Scenario-definition structural diff

```console
scenario --json diff-definition "$DSE_DEMO/scenario-before.yaml" "$DSE_DEMO/scenario-after.yaml" > "$DSE_DEMO/definition-diff.json"
```

This validates and structurally compares two definitions; it is not a textual
YAML diff. Formatting-only and mapping-key-order-only changes are ignored.
Changes use `scenario.semantic-address/1`, and JSON uses
`scenario.definition-diff/1`. Definition diff does not automatically perform
impact analysis and does not prove behavioral equivalence.

## Conservative impact analysis

```console
scenario --json impact "$DSE_DEMO/scenario-before.yaml" "$DSE_DEMO/scenario-after.yaml" > "$DSE_DEMO/impact.json"
```

The `scenario.impact/1` result is conservative static may-impact analysis over
the structural change set. Classifications are `DIRECT`,
`TRANSITIVE_POSSIBLE`, and `UNKNOWN`; **UNKNOWN does not mean unaffected**. No
behavioral-equivalence or complete-impact proof is claimed. Amplification is the
reduced fraction of distinct affected semantic-addressed entities over distinct
eligible entities in the bounded union of the validated dependency graphs; it is
not a probability.

## Export → verify

Create the installed package's deterministic reference evidence bundle through
its stable public reference-pack API, then use only public CLI commands:

```console
python3 - <<'PY'
from pathlib import Path
import os
from scenario_engine.reference_packs import export_ecommerce_evidence
export_ecommerce_evidence(Path(os.environ['DSE_DEMO']) / 'evidence')
PY
scenario verify "$DSE_DEMO/evidence"
scenario export "$DSE_DEMO/evidence" "$DSE_DEMO/evidence-copy"
scenario verify "$DSE_DEMO/evidence-copy"
```

Evidence roots and the absent export destination are absolute local filesystem
paths. Export validates and copies the existing evidence contract; it does not
introduce another evidence format.

## Evidence/result → static trace viewer

```console
scenario trace-view "$DSE_DEMO/result.json" --out "$DSE_DEMO/trace.html"
open "$DSE_DEMO/trace.html"
```

The source and absent destination are absolute local filesystem paths. The
command accepts `scenario.result/1` and `suite.run/1` and writes exactly one
self-contained `scenario.trace-view/1` HTML file. It is offline, read-only, and
uses no server, network, telemetry, CDN assets, or source mutation. Open the file
directly in a browser. Actor-aware `scenario.result/2` evidence uses the same
command and contract; optional matching scheduler context is supplied explicitly:

```console
scenario trace-view "$DSE_DEMO/result-v2.json" --schedule "$DSE_DEMO/schedule.json" --out "$DSE_DEMO/trace-v2.html"
```

Without `--schedule`, Result/2 committed history and actor lanes remain available
and scheduler-selection context is labeled unavailable. The public Python form is
`render_trace_view(result)` or `render_trace_view(result, schedule=schedule)` from
`scenario_engine.trace_view`. Static hash/linkage checks do not claim exact replay;
the viewer always labels exact execution replay as not performed. Open it
locally. The viewer displays only evidence present in the input; it never reruns
the scenario or reconstructs missing runtime state.

## Scaffold → inspect → validate → review/freeze → later run

```console
scenario scaffold reviewed_draft --step prepare --step finish > "$DSE_DEMO/draft.yaml"
cat "$DSE_DEMO/draft.yaml"
scenario validate "$DSE_DEMO/draft.yaml"
# Human review and freeze happen here.
scenario --json run "$DSE_DEMO/draft.yaml" --seed reviewed-seed > "$DSE_DEMO/draft-result.json"
```

`scenario scaffold` uses the offline deterministic default provider. It requires
no API key and no runtime LLM, does not advertise or contact an LLM provider,
and never executes automatically. Its `scenario.scaffold/1` metadata has no
runtime authority. Generated DSL remains an untrusted proposal until ordinary
validation passes; inspect it and human-review/freeze it before explicitly
running it later.

## Human and machine diagnostics

Default mode emits bounded actionable human diagnostics. Exact human prose and
layout are presentation, not a stable automation interface. Put `--json` before
the command to receive the `scenario.error/1` machine-readable error envelope on
stderr. Automation should rely on `schema`, `code`, `category`, `exit_code`, and,
when applicable, `semantic_path`.

Commands that say **absolute local filesystem path** reject relative paths and
remote or URI-like sources. Other source arguments are explicit local files (or
stdin where their help permits it). No workflow above uses a remote URI.
