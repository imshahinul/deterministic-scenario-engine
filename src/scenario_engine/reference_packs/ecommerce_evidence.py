"""Bounded ecommerce Domain Pack and deterministic evidence demonstrator.

The pack is declarative.  This module's workflow explicitly validates it against
a fresh ecommerce plugin registry before invoking the existing execution,
inspection, assertion, diff, replay, and evidence APIs.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import tempfile

from scenario_engine.diff import SemanticDiff, canonical_diff_bytes, semantic_diff
from scenario_engine.domain_packs import DomainPack, DomainPackRegistry, PluginRequirement
from scenario_engine.dsl import compile_document, parse_yaml, replay_scenario, run_scenario
from scenario_engine.evidence import (
    EvidenceBundle,
    EvidenceEntry,
    EvidenceProvenance,
    EvidenceRelationship,
    EvidenceType,
    export_evidence_bundle,
)
from scenario_engine.inspection import (
    InspectionDocument,
    canonical_inspection_bytes,
    inspect_result,
)
from scenario_engine.oracle_assertions import (
    OracleAssertion,
    OracleAssertionEvaluation,
    OracleAssertionKind,
    OracleAssertionOutcome,
    canonical_evaluation_bytes,
    evaluate_assertions,
)
from scenario_engine.result import ScenarioResult
from scenario_engine.values import MISSING, canonical_bytes

from .ecommerce import VERSION as PLUGIN_VERSION
from .ecommerce import ecommerce_registry


DOMAIN_PACK_NAME = "ecommerce.reference_evidence"
DOMAIN_PACK_VERSION = "1"
ROOT_SEED = "phase-3.8-ecommerce-evidence"
RUN_INDEX = 0
LOCALE = "en_US"
BASELINE_INPUTS = {"email_domain": "example.test"}
VARIANT_INPUTS = {"email_domain": "variant.test"}

SCENARIO_YAML = '''dsl_version: 1
scenario: ecommerce_reference_evidence
clock: {start: "2026-08-15T10:30:00Z"}
resources:
  email_domain: {$input: email_domain}
  item_prefix: {$literal: REF}
initial_state:
  status: new
  customer_email: null
  sku: null
  order_number: null
  tracking_number: null
  paid: false
steps:
  - id: create_customer
    generate:
      customer_email:
        $plugin:
          name: ecommerce.customer_email
          version: "1"
          args:
            domain: {$resource: email_domain}
            prefix: {$literal: shopper}
    write:
      customer_email: {$local: customer_email}
      status: {$literal: customer_created}
    emit:
      - type: customer_created
        fields: {customer_email: {$state: customer_email}}
    advance: {seconds: 1}
    transition: create_cart
  - id: create_cart
    generate:
      sku:
        $plugin:
          name: ecommerce.sku
          version: "1"
          args: {prefix: {$resource: item_prefix}}
    write:
      sku: {$local: sku}
      status: {$literal: cart_ready}
    emit:
      - type: cart_ready
        fields: {sku: {$state: sku}}
    advance: {seconds: 2}
    transition: create_order
  - id: create_order
    generate:
      order_number:
        $plugin:
          name: ecommerce.order_number
          version: "1"
          args: {prefix: {$literal: ORD}}
    write:
      order_number: {$local: order_number}
      status: {$literal: order_created}
    emit:
      - type: order_created
        fields:
          customer_email: {$state: customer_email}
          order_number: {$state: order_number}
          sku: {$state: sku}
    advance: {seconds: 3}
    transition: checkout
  - id: checkout
    write:
      paid: {$literal: true}
      status: {$literal: payment_captured}
    emit:
      - type: payment_captured
        fields: {order_number: {$state: order_number}}
    advance: {seconds: 4}
    transition: ship
  - id: ship
    generate:
      tracking_number:
        $plugin:
          name: ecommerce.tracking_number
          version: "1"
          args: {prefix: {$literal: SYN}}
    write:
      tracking_number: {$local: tracking_number}
      status: {$literal: shipped}
    emit:
      - type: shipment_created
        fields:
          order_number: {$state: order_number}
          tracking_number: {$state: tracking_number}
    advance: {seconds: 5}
    transition: null
'''

_ASSERTION_DECLARATIONS = (
    {"assertion_id": "final-state-shipped", "kind": "equal", "target": "/final_state/status", "expected": "shipped"},
    {"assertion_id": "payment-captured", "kind": "equal", "target": "/final_state/paid", "expected": True},
    {"assertion_id": "five-artifacts", "kind": "count", "target": "/artifacts", "expected": 5},
    {"assertion_id": "lifecycle-order", "kind": "transition_order", "target": "/history", "expected": ["create_cart", "create_order", "checkout", "ship"]},
    {"assertion_id": "tracking-present", "kind": "present", "target": "/final_state/tracking_number"},
)


def ecommerce_domain_pack() -> DomainPack:
    """Return a fresh immutable ecommerce reference Domain Pack."""
    return DomainPack(
        name=DOMAIN_PACK_NAME,
        version=DOMAIN_PACK_VERSION,
        resource_templates={"baseline": BASELINE_INPUTS, "variant": VARIANT_INPUTS},
        oracle_fragments={"lifecycle": _ASSERTION_DECLARATIONS},
        documentation={"scenario.dsl1": SCENARIO_YAML},
        plugin_requirements=tuple(
            PluginRequirement(name, PLUGIN_VERSION)
            for name in (
                "ecommerce.customer_email",
                "ecommerce.sku",
                "ecommerce.order_number",
                "ecommerce.tracking_number",
            )
        ),
    )


@dataclass(frozen=True, slots=True)
class EcommerceEvidenceWorkflow:
    """Recorded products of one completed reference workflow."""

    domain_pack: DomainPack
    baseline: ScenarioResult
    replay: ScenarioResult
    inspection: InspectionDocument
    evaluation: OracleAssertionEvaluation
    variant: ScenarioResult
    difference: SemanticDiff
    bundle: EvidenceBundle


def _assertions(pack: DomainPack) -> tuple[OracleAssertion, ...]:
    return tuple(
        OracleAssertion(
            assertion_id=item["assertion_id"],
            kind=OracleAssertionKind(item["kind"]),
            target=item["target"],
            expected=item["expected"] if "expected" in item else MISSING,
        )
        for item in pack.oracle_fragments["lifecycle"]
    )


def _entry(logical_id: str, evidence_type: EvidenceType, artifact_schema: str,
           path: str, data: bytes, source_sha256: str, contract: str) -> EvidenceEntry:
    return EvidenceEntry(
        logical_id=logical_id,
        evidence_type=evidence_type,
        artifact_schema=artifact_schema,
        media_type="application/json",
        path=path,
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        provenance=EvidenceProvenance(source_sha256, contract),
    )


def export_ecommerce_evidence(destination: str | Path) -> EcommerceEvidenceWorkflow:
    """Run and atomically export the fixed ecommerce evidence workflow.

    ``destination`` must satisfy the accepted evidence export destination rules.
    No Domain Pack, plugin registry, or execution setting is selected implicitly.
    """
    target = Path(destination).absolute()
    pack = ecommerce_domain_pack()
    registry = ecommerce_registry()
    DomainPackRegistry((pack,)).validate_plugins(pack, registry)
    scenario_text = pack.documentation["scenario.dsl1"]
    scenario = compile_document(parse_yaml(scenario_text))

    baseline = run_scenario(
        scenario, ROOT_SEED, run_index=RUN_INDEX, locale=LOCALE,
        inputs=dict(pack.resource_templates["baseline"]), plugins=registry,
    )
    replay = replay_scenario(
        scenario_text, baseline.manifest,
        inputs=dict(pack.resource_templates["baseline"]), plugins=ecommerce_registry(),
    )
    if replay != baseline or replay.to_json_bytes() != baseline.to_json_bytes():
        raise RuntimeError("ecommerce reference replay did not preserve exact result bytes")

    inspection = inspect_result(baseline)
    evaluation = evaluate_assertions(inspection, _assertions(pack))
    if any(result.outcome is not OracleAssertionOutcome.PASS for result in evaluation.results):
        raise RuntimeError("ecommerce reference Oracle Assertion evaluation did not pass")
    variant = run_scenario(
        scenario, ROOT_SEED, run_index=RUN_INDEX, locale=LOCALE,
        inputs=dict(pack.resource_templates["variant"]), plugins=ecommerce_registry(),
    )
    difference = semantic_diff(baseline, variant, max_records=64)
    if difference.equal:
        raise RuntimeError("ecommerce reference variant did not produce a semantic difference")

    baseline_bytes = baseline.to_json_bytes()
    manifest_bytes = canonical_bytes(baseline.manifest.normalized())
    inspection_bytes = canonical_inspection_bytes(inspection)
    evaluation_bytes = canonical_evaluation_bytes(evaluation)
    variant_bytes = variant.to_json_bytes()
    diff_bytes = canonical_diff_bytes(difference)
    scenario_hash = baseline.manifest.scenario_canonical_hash
    payloads = {
        "artifacts/baseline-result.json": baseline_bytes,
        "artifacts/baseline-manifest.json": manifest_bytes,
        "artifacts/baseline-inspection.json": inspection_bytes,
        "artifacts/oracle-evaluation.json": evaluation_bytes,
        "artifacts/variant-result.json": variant_bytes,
        "artifacts/semantic-diff.json": diff_bytes,
    }
    baseline_hash = hashlib.sha256(baseline_bytes).hexdigest()
    inspection_hash = hashlib.sha256(inspection_bytes).hexdigest()
    variant_hash = hashlib.sha256(variant_bytes).hexdigest()
    entries = (
        _entry("baseline.result", EvidenceType.RESULT, "scenario.result/1", "artifacts/baseline-result.json", baseline_bytes, scenario_hash, "scenario.dsl/1"),
        _entry("baseline.manifest", EvidenceType.MANIFEST, "scenario.manifest/1", "artifacts/baseline-manifest.json", manifest_bytes, scenario_hash, "scenario.dsl/1"),
        _entry("baseline.inspection", EvidenceType.INSPECTION, "inspection.document/1", "artifacts/baseline-inspection.json", inspection_bytes, baseline_hash, "inspection.document/1"),
        _entry("baseline.evaluation", EvidenceType.EVALUATION, "oracle.evaluation/1", "artifacts/oracle-evaluation.json", evaluation_bytes, inspection_hash, "oracle.evaluation/1"),
        _entry("variant.result", EvidenceType.RESULT, "scenario.result/1", "artifacts/variant-result.json", variant_bytes, scenario_hash, "scenario.dsl/1"),
        _entry("baseline-variant.diff", EvidenceType.DIFF, "semantic.diff/1", "artifacts/semantic-diff.json", diff_bytes, variant_hash, "semantic.diff/1"),
    )
    bundle = EvidenceBundle(entries, (
        EvidenceRelationship("baseline.result", "baseline.inspection", "derived-inspection"),
        EvidenceRelationship("baseline.inspection", "baseline.evaluation", "evaluated-by-oracle"),
        EvidenceRelationship("baseline.result", "baseline-variant.diff", "compared-by-diff"),
        EvidenceRelationship("variant.result", "baseline-variant.diff", "compared-by-diff"),
    ))

    with tempfile.TemporaryDirectory(
        prefix=".dse-ecommerce-evidence-", dir=target.parent,
    ) as directory:
        source = Path(directory)
        for relative, data in payloads.items():
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        export_evidence_bundle(bundle, source_root=source, destination=target)
    return EcommerceEvidenceWorkflow(
        pack, baseline, replay, inspection, evaluation, variant, difference, bundle,
    )


__all__ = (
    "BASELINE_INPUTS",
    "DOMAIN_PACK_NAME",
    "DOMAIN_PACK_VERSION",
    "EcommerceEvidenceWorkflow",
    "LOCALE",
    "ROOT_SEED",
    "RUN_INDEX",
    "SCENARIO_YAML",
    "VARIANT_INPUTS",
    "ecommerce_domain_pack",
    "export_ecommerce_evidence",
)
