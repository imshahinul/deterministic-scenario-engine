# Product evidence gate

A successfully shipped phase does not automatically authorize design or
implementation of the next feature phase.

## Demand evidence requirement

Before Phase 4 product scope can be frozen, every proposed substantial
capability must trace to credible evidence of an actual problem. Acceptable
evidence includes:

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

No Phase 4 architecture freeze or implementation prompt is authorized until an
evidence packet exists. For every candidate substantial feature, it must record:

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

## Adoption observation

Downloads, stars, forks, clones, and traffic may be recorded as context but do
not prove a feature need. Preferred evidence combines a specific observed
problem, credible user/workflow context, and repeatability or consequence.
Quantitative adoption data is supporting evidence, not the product requirement.

Until qualifying external problem evidence and the required packet exist:

```text
PHASE4_AUTHORIZED=NO
PHASE4_ARCHITECTURE_STARTED=NO
PHASE4_IMPLEMENTATION_STARTED=NO
NEXT_ACTIVITY=ADOPTION_AND_PROBLEM_OBSERVATION
```
