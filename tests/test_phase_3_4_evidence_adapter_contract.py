from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
import importlib
import importlib.metadata
import os
import socket
import subprocess
import threading
import time
from unittest.mock import patch

import pytest

from scenario_engine.evidence import (
    DEFAULT_ADAPTER_IN_FLIGHT,
    EVIDENCE_ADAPTER_CAPABILITY_SCHEMA_VERSION,
    EVIDENCE_ADAPTER_CONTRACT_VERSION,
    EVIDENCE_ADAPTER_RECEIPT_SCHEMA_VERSION,
    MAX_ADAPTER_IN_FLIGHT,
    MAX_ADAPTER_RECEIPT_BYTES,
    MAX_ADAPTER_RECEIPTS_BYTES,
    EvidenceAdapterBoundError,
    EvidenceAdapterCapability,
    EvidenceAdapterContractError,
    EvidenceAdapterOrchestrationError,
    EvidenceAdapterPublication,
    EvidenceAdapterReceipt,
    EvidenceAdapterReceiptStatus,
    EvidenceBundle,
    canonical_adapter_capability_bytes,
    canonical_adapter_receipt_bytes,
    publish_evidence_bundles,
)


class FakeAdapter:
    def __init__(self, *, fail=(), delays=None, locator_prefix="fake://bundle") -> None:
        self.capability = EvidenceAdapterCapability("test.fake", "1.0.0")
        self.fail = set(fail)
        self.delays = delays or {}
        self.locator_prefix = locator_prefix
        self.calls = []
        self._positions = {}
        self.active = 0
        self.maximum_active = 0
        self.lock = threading.Lock()

    def publish_bundle(self, bundle: EvidenceBundle) -> EvidenceAdapterPublication:
        with self.lock:
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
            logical_id = bundle.entries[0].logical_id if bundle.entries else "result:0"
            suffix = logical_id.rsplit(":", 1)[-1]
            position = int(suffix) if suffix.isdigit() else self._positions.setdefault(
                bundle.bundle_id, len(self._positions)
            )
            self.calls.append(bundle.bundle_id)
        try:
            time.sleep(self.delays.get(position, 0))
            if position in self.fail:
                raise RuntimeError("token=SECRET account=/private/provider/path")
            return EvidenceAdapterPublication(f"{self.locator_prefix}/{bundle.bundle_id}")
        finally:
            with self.lock:
                self.active -= 1


def bundles(count: int) -> tuple[EvidenceBundle, ...]:
    from scenario_engine.evidence import EvidenceEntry, EvidenceType

    return tuple(
        EvidenceBundle((EvidenceEntry(
            f"result:{position}", EvidenceType.RESULT, "suite.run/1", "application/json",
            f"results/{position}.json", f"{position:064x}", 0,
        ),))
        for position in range(count)
    )


def test_contract_versions_capability_canonicalization_and_immutability() -> None:
    capability = EvidenceAdapterCapability("test.fake", "1.0.0")
    assert EVIDENCE_ADAPTER_CONTRACT_VERSION == "evidence.adapter/1"
    assert EVIDENCE_ADAPTER_CAPABILITY_SCHEMA_VERSION == "evidence.adapter-capability/1"
    assert EVIDENCE_ADAPTER_RECEIPT_SCHEMA_VERSION == "evidence.adapter-receipt/1"
    assert canonical_adapter_capability_bytes(capability) == (
        b'{"adapter_contract":"evidence.adapter/1","adapter_id":"test.fake",'
        b'"adapter_version":"1.0.0","operations":["publish-bundle"],'
        b'"schema_version":"evidence.adapter-capability/1"}'
    )
    with pytest.raises(FrozenInstanceError):
        capability.adapter_id = "changed"  # type: ignore[misc]
    with pytest.raises(EvidenceAdapterBoundError, match="adapter_version"):
        EvidenceAdapterCapability("test.fake", "v" * 129)
    with pytest.raises(EvidenceAdapterContractError, match="operations"):
        EvidenceAdapterCapability("test.fake", "1", ())
    with pytest.raises(EvidenceAdapterContractError, match="contract version"):
        EvidenceAdapterCapability("test.fake", "1", adapter_contract="evidence.adapter/2")


def test_explicit_adapter_success_normalized_receipt_and_canonical_bytes() -> None:
    bundle = EvidenceBundle(())
    adapter = FakeAdapter(locator_prefix="urn:test")
    receipts = publish_evidence_bundles(adapter, (bundle,))
    receipt = receipts[0]
    assert receipt == EvidenceAdapterReceipt(
        "test.fake", "1.0.0", bundle.bundle_id, 0,
        EvidenceAdapterReceiptStatus.SUCCESS,
        external_locator=f"urn:test/{bundle.bundle_id}",
    )
    encoded = canonical_adapter_receipt_bytes(receipt)
    assert encoded == canonical_adapter_receipt_bytes(receipt)
    assert json.loads(encoded) == {
        "adapter_id": "test.fake", "adapter_version": "1.0.0",
        "error_code": None, "external_locator": f"urn:test/{bundle.bundle_id}",
        "operation": "publish-bundle", "ordinal": 0,
        "schema_version": "evidence.adapter-receipt/1",
        "source_bundle_id": bundle.bundle_id, "status": "success",
    }
    assert adapter.calls == [bundle.bundle_id]


def test_protocol_missing_method_wrong_return_and_capability_mismatch() -> None:
    class Missing:
        capability = EvidenceAdapterCapability("test.missing", "1")

    class Wrong(FakeAdapter):
        def publish_bundle(self, bundle):
            return {"locator": "raw-provider-object"}

    class WrongCapability(FakeAdapter):
        capability = object()

        def __init__(self):
            pass

    with pytest.raises(EvidenceAdapterContractError, match="does not implement"):
        publish_evidence_bundles(Missing(), ())  # type: ignore[arg-type]
    with pytest.raises(EvidenceAdapterContractError, match="wrong type"):
        publish_evidence_bundles(Wrong(), bundles(1))
    with pytest.raises(EvidenceAdapterContractError, match="capability has the wrong type"):
        publish_evidence_bundles(WrongCapability(), ())


def test_order_is_input_order_independent_of_completion_and_worker_count() -> None:
    items = bundles(4)
    concurrent = publish_evidence_bundles(
        FakeAdapter(delays={0: 0.04, 1: 0.03, 2: 0.02, 3: 0.01}),
        items, workers=4, max_in_flight=4,
    )
    serial = publish_evidence_bundles(FakeAdapter(), items, workers=1, max_in_flight=1)
    assert [item.ordinal for item in concurrent] == [0, 1, 2, 3]
    assert b"".join(map(canonical_adapter_receipt_bytes, concurrent)) == b"".join(
        map(canonical_adapter_receipt_bytes, serial)
    )


def test_failure_is_isolated_normalized_and_secret_is_not_persisted() -> None:
    receipts = publish_evidence_bundles(
        FakeAdapter(fail={1}), bundles(3), workers=2, max_in_flight=2,
    )
    assert [item.status for item in receipts] == [
        EvidenceAdapterReceiptStatus.SUCCESS,
        EvidenceAdapterReceiptStatus.FAILURE,
        EvidenceAdapterReceiptStatus.SUCCESS,
    ]
    failed = receipts[1]
    assert failed.error_code == "adapter.operation_failed"
    assert failed.external_locator is None
    encoded = canonical_adapter_receipt_bytes(failed)
    assert b"SECRET" not in encoded and b"private/provider" not in encoded


def test_individual_and_aggregate_receipt_bounds_use_canonical_bytes() -> None:
    exact = EvidenceAdapterPublication("x" * 100)
    assert exact.external_locator == "x" * 100
    with pytest.raises(EvidenceAdapterBoundError, match="external_locator"):
        EvidenceAdapterPublication("x" * (MAX_ADAPTER_RECEIPT_BYTES + 1))
    oversized = EvidenceAdapterPublication("x" * MAX_ADAPTER_RECEIPT_BYTES)

    class Oversized(FakeAdapter):
        def publish_bundle(self, bundle):
            return oversized

    with pytest.raises(EvidenceAdapterBoundError, match="adapter receipt"):
        publish_evidence_bundles(Oversized(), bundles(1))
    with pytest.raises(EvidenceAdapterBoundError, match="aggregate"):
        publish_evidence_bundles(FakeAdapter(), bundles(1), max_receipts_bytes=1)
    for invalid in (-1, True, 1.5, MAX_ADAPTER_RECEIPTS_BYTES + 1):
        with pytest.raises(EvidenceAdapterBoundError, match="max_receipts_bytes"):
            publish_evidence_bundles(FakeAdapter(), (), max_receipts_bytes=invalid)  # type: ignore[arg-type]


def test_backpressure_limits_active_work_and_does_not_eagerly_exhaust_iterator() -> None:
    adapter = FakeAdapter(delays={position: 0.01 for position in range(12)})
    publish_evidence_bundles(adapter, bundles(12), workers=4, max_in_flight=4)
    assert adapter.maximum_active <= 4
    assert (DEFAULT_ADAPTER_IN_FLIGHT, MAX_ADAPTER_IN_FLIGHT) == (64, 1024)
    default_adapter = FakeAdapter(delays={position: 0.005 for position in range(70)})
    publish_evidence_bundles(default_adapter, bundles(70), workers=64)
    assert default_adapter.maximum_active <= DEFAULT_ADAPTER_IN_FLIGHT
    for invalid in (0, True, 1.5, MAX_ADAPTER_IN_FLIGHT + 1):
        with pytest.raises(EvidenceAdapterBoundError, match="max_in_flight"):
            publish_evidence_bundles(FakeAdapter(), (), max_in_flight=invalid)  # type: ignore[arg-type]

    consumed = []

    def guarded():
        for position in range(6):
            if position >= 3 and len(adapter.calls) < 1:
                raise AssertionError("iterator was exhausted before bounded work began")
            consumed.append(position)
            yield EvidenceBundle(())

    adapter = FakeAdapter(delays={0: 0.01})
    assert len(publish_evidence_bundles(adapter, guarded(), workers=1, max_in_flight=3)) == 6
    assert consumed == list(range(6))


def test_invalid_request_and_iterable_failure_are_typed_before_or_at_boundary() -> None:
    adapter = FakeAdapter()
    with pytest.raises(EvidenceAdapterContractError, match="EvidenceBundle"):
        publish_evidence_bundles(adapter, (object(),))  # type: ignore[arg-type]
    assert adapter.calls == []

    def broken():
        yield EvidenceBundle(())
        raise RuntimeError("secret iterator diagnostic")

    with pytest.raises(EvidenceAdapterOrchestrationError, match="iterable failed"):
        publish_evidence_bundles(FakeAdapter(), broken(), max_in_flight=1)


def test_core_has_no_discovery_or_ambient_authority_and_bundle_cannot_select_adapter() -> None:
    bundle = EvidenceBundle(())
    adapter = FakeAdapter()
    environment = dict(os.environ)
    real_import_module = importlib.import_module
    real_entry_points = importlib.metadata.entry_points
    with (
        patch.object(time, "time", side_effect=AssertionError("semantic clock accessed")),
        patch("random.random", side_effect=AssertionError("randomness accessed")),
        patch.object(socket, "create_connection", side_effect=AssertionError("network accessed")),
        patch.object(socket.socket, "connect", side_effect=AssertionError("socket accessed")),
        patch.object(subprocess, "run", side_effect=AssertionError("subprocess accessed")),
        patch.object(importlib, "import_module", side_effect=AssertionError("dynamic import accessed")),
        patch.object(importlib.metadata, "entry_points", side_effect=AssertionError("discovery accessed")),
    ):
        receipts = publish_evidence_bundles(adapter, (bundle,))
    assert receipts[0].adapter_id == "test.fake"
    assert dict(os.environ) == environment
    import scenario_engine.evidence as evidence
    assert not hasattr(evidence, "get_adapter")
    assert not hasattr(evidence, "discover_adapters")
    assert not hasattr(evidence, "ADAPTERS")
