# Product evidence gate

A successfully shipped phase does not automatically authorize implementation
of the next feature phase.

## Demand evidence requirement

Before a Phase 4 capability may enter implementation MUST or SHOULD scope, it
must trace to credible evidence of an actual problem. Acceptable evidence
includes:

- an external user report or request;
- a public issue or discussion describing real friction;
- observed integration failure or friction;
- a repeated support question;
- a real downstream implementation needing the capability;
- credible usage or adoption evidence combined with a specific observed
  problem.

The following is insufficient by itself: ability to build something,
architectural fit or elegance, previous deferral, download counts, GitHub stars,
benchmark opportunities, or feature parity with another tool.

## Maintenance exceptions

Product-demand evidence is not required before addressing a confirmed bug,
security vulnerability, compatibility regression, release-integrity defect,
dependency or platform breakage, data-loss or correctness issue, or maintenance
needed to preserve an existing public contract. Such work instead requires
evidence of the defect or risk.

## Phase 4 evidence packet

No Phase 4 implementation checkpoint or prompt is authorized until an evidence
packet exists. For every candidate substantial feature, it must record:

- problem statement;
- evidence source and date;
- affected user or workflow;
- observed current workaround or failure;
- why DSE itself should solve the problem;
- why external tooling is insufficient;
- minimum useful outcome;
- evidence strength.

Classify each candidate as `SUPPORTED_BY_EVIDENCE`, `WEAK_EVIDENCE`, or
`NO_EVIDENCE`. Only supported items may enter MUST or SHOULD scope. Weak items
remain observational; unsupported items go to the parking lot or are deferred.
This policy does not itself create a Phase 4 feature list.

## Prospective architecture authorization

Phase 4 architecture, scope, and design contracts may be researched, specified,
reviewed, and frozen prospectively while evidence remains insufficient. Such
work must remain conditional: it does not assert product demand, authorize
implementation, or turn internal hypotheses into requirements. It may define
bounded future surfaces only, classified as `CONDITIONAL_CANDIDATE_SURFACE` or
an equivalent explicitly conditional term.

An architecture freeze does not make an unvalidated hypothesis eligible for
MUST or SHOULD scope. Only `SUPPORTED_BY_EVIDENCE` items may enter
implementation MUST or SHOULD scope. Implementation of Phase 4 product
functionality requires separate satisfaction of this external Product Evidence
Gate before any Phase 4 implementation checkpoint begins.

## Adoption observation

Downloads, stars, forks, clones, and traffic may be recorded as context but do
not prove a feature need. Preferred evidence combines a specific observed
problem, credible user/workflow context, and repeatability or consequence.
Quantitative adoption data is supporting evidence, not the product requirement.

Until qualifying external problem evidence and the required packet exist:

```text
PHASE4_EVIDENCE_STATE=INSUFFICIENT
PHASE4_ARCHITECTURE_FREEZE_AUTHORIZED=YES
PHASE4_IMPLEMENTATION_AUTHORIZED=NO
PHASE4_ARCHITECTURE_STARTED=NO
PHASE4_IMPLEMENTATION_STARTED=NO
NEXT_ACTIVITY=PHASE4_0_ARCHITECTURE_FREEZE
```

The next activity authorizes architecture/design work only. It does not
authorize Phase 4.1 or any product implementation.
