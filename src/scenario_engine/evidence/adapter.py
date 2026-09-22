"""Explicit trusted adapter contract and bounded publication orchestration."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Protocol, runtime_checkable

from .canonical import _canonical_json_bytes
from .errors import (
    EvidenceAdapterError,
    EvidenceAdapterBoundError,
    EvidenceAdapterContractError,
    EvidenceAdapterOrchestrationError,
)
from .models import EvidenceBundle, _contract, _identifier, _sha256


EVIDENCE_ADAPTER_CONTRACT_VERSION = "evidence.adapter/1"
EVIDENCE_ADAPTER_CAPABILITY_SCHEMA_VERSION = "evidence.adapter-capability/1"
EVIDENCE_ADAPTER_RECEIPT_SCHEMA_VERSION = "evidence.adapter-receipt/1"
EVIDENCE_ADAPTER_PUBLISH_OPERATION = "publish-bundle"

DEFAULT_ADAPTER_IN_FLIGHT = 64
MAX_ADAPTER_IN_FLIGHT = 1_024
MAX_ADAPTER_RECEIPT_BYTES = 1 * 1024 * 1024
MAX_ADAPTER_RECEIPTS_BYTES = 16 * 1024 * 1024
MAX_ADAPTER_VERSION_BYTES = 128
MAX_EXTERNAL_LOCATOR_BYTES = 1 * 1024 * 1024


def _bounded_utf8(value: object, name: str, maximum: int, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or not value:
        raise EvidenceAdapterContractError(f"{name} must be a non-empty string")
    if len(value.encode("utf-8")) > maximum:
        raise EvidenceAdapterBoundError(f"{name} exceeds the {maximum}-byte ceiling")
    return value


def _adapter_identifier(value: object) -> str:
    try:
        return _identifier(value, "adapter_id")
    except Exception as error:
        raise EvidenceAdapterContractError(str(error)) from None


def _adapter_contract(value: object) -> str:
    try:
        return _contract(value, "adapter_contract")
    except Exception as error:
        raise EvidenceAdapterContractError(str(error)) from None


@dataclass(frozen=True, slots=True)
class EvidenceAdapterCapability:
    """Immutable provider-neutral declaration made by one adapter instance."""

    adapter_id: str
    adapter_version: str
    operations: tuple[str, ...] = (EVIDENCE_ADAPTER_PUBLISH_OPERATION,)
    adapter_contract: str = EVIDENCE_ADAPTER_CONTRACT_VERSION
    schema_version: str = EVIDENCE_ADAPTER_CAPABILITY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EVIDENCE_ADAPTER_CAPABILITY_SCHEMA_VERSION:
            raise EvidenceAdapterContractError("unsupported adapter capability schema version")
        if self.adapter_contract != EVIDENCE_ADAPTER_CONTRACT_VERSION:
            raise EvidenceAdapterContractError("unsupported evidence adapter contract version")
        object.__setattr__(self, "adapter_id", _adapter_identifier(self.adapter_id))
        object.__setattr__(
            self, "adapter_version",
            _bounded_utf8(self.adapter_version, "adapter_version", MAX_ADAPTER_VERSION_BYTES),
        )
        if not isinstance(self.operations, tuple) or self.operations != (
            EVIDENCE_ADAPTER_PUBLISH_OPERATION,
        ):
            raise EvidenceAdapterContractError(
                "operations must declare exactly the publish-bundle operation"
            )
        encoded = _canonical_json_bytes(self)
        if len(encoded) > MAX_ADAPTER_RECEIPT_BYTES:
            raise EvidenceAdapterBoundError("adapter capability exceeds the canonical byte ceiling")


@dataclass(frozen=True, slots=True)
class EvidenceAdapterPublication:
    """Bounded external observation returned by a successful adapter call."""

    external_locator: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "external_locator",
            _bounded_utf8(
                self.external_locator, "external_locator", MAX_EXTERNAL_LOCATOR_BYTES,
                optional=True,
            ),
        )


class EvidenceAdapterReceiptStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"


@dataclass(frozen=True, slots=True)
class EvidenceAdapterReceipt:
    """Canonical normalized result for one explicit adapter operation."""

    adapter_id: str
    adapter_version: str
    source_bundle_id: str
    ordinal: int
    status: EvidenceAdapterReceiptStatus
    external_locator: str | None = None
    error_code: str | None = None
    operation: str = EVIDENCE_ADAPTER_PUBLISH_OPERATION
    schema_version: str = EVIDENCE_ADAPTER_RECEIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EVIDENCE_ADAPTER_RECEIPT_SCHEMA_VERSION:
            raise EvidenceAdapterContractError("unsupported adapter receipt schema version")
        object.__setattr__(self, "adapter_id", _adapter_identifier(self.adapter_id))
        object.__setattr__(
            self, "adapter_version",
            _bounded_utf8(self.adapter_version, "adapter_version", MAX_ADAPTER_VERSION_BYTES),
        )
        try:
            source_bundle_id = _sha256(self.source_bundle_id, "source_bundle_id")
        except Exception as error:
            raise EvidenceAdapterContractError(str(error)) from None
        object.__setattr__(self, "source_bundle_id", source_bundle_id)
        if isinstance(self.ordinal, bool) or not isinstance(self.ordinal, int) or self.ordinal < 0:
            raise EvidenceAdapterContractError("ordinal must be a nonnegative integer")
        if not isinstance(self.status, EvidenceAdapterReceiptStatus):
            raise EvidenceAdapterContractError("status must be an EvidenceAdapterReceiptStatus")
        if self.operation != EVIDENCE_ADAPTER_PUBLISH_OPERATION:
            raise EvidenceAdapterContractError("unsupported adapter operation")
        object.__setattr__(
            self, "external_locator",
            _bounded_utf8(
                self.external_locator, "external_locator", MAX_EXTERNAL_LOCATOR_BYTES,
                optional=True,
            ),
        )
        if self.status is EvidenceAdapterReceiptStatus.SUCCESS:
            if self.error_code is not None:
                raise EvidenceAdapterContractError("successful receipt cannot contain error_code")
        else:
            if self.external_locator is not None:
                raise EvidenceAdapterContractError("failed receipt cannot contain external_locator")
            if self.error_code != "adapter.operation_failed":
                raise EvidenceAdapterContractError(
                    "failed receipt requires the normalized adapter.operation_failed code"
                )
        if len(_canonical_json_bytes(self)) > MAX_ADAPTER_RECEIPT_BYTES:
            raise EvidenceAdapterBoundError(
                f"adapter receipt exceeds the {MAX_ADAPTER_RECEIPT_BYTES}-byte ceiling"
            )


@runtime_checkable
class EvidenceAdapter(Protocol):
    """Structural contract for explicit trusted unsandboxed Python adapters."""

    @property
    def capability(self) -> EvidenceAdapterCapability: ...

    def publish_bundle(self, bundle: EvidenceBundle) -> EvidenceAdapterPublication: ...


def canonical_adapter_capability_bytes(capability: EvidenceAdapterCapability) -> bytes:
    """Return canonical UTF-8 JSON for one validated capability declaration."""
    if not isinstance(capability, EvidenceAdapterCapability):
        raise EvidenceAdapterContractError("capability must be an EvidenceAdapterCapability")
    return _canonical_json_bytes(capability)


def canonical_adapter_receipt_bytes(receipt: EvidenceAdapterReceipt) -> bytes:
    """Return canonical UTF-8 JSON for one normalized receipt."""
    if not isinstance(receipt, EvidenceAdapterReceipt):
        raise EvidenceAdapterContractError("receipt must be an EvidenceAdapterReceipt")
    encoded = _canonical_json_bytes(receipt)
    if len(encoded) > MAX_ADAPTER_RECEIPT_BYTES:
        raise EvidenceAdapterBoundError(
            f"adapter receipt exceeds the {MAX_ADAPTER_RECEIPT_BYTES}-byte ceiling"
        )
    return encoded


def _validate_options(adapter: object, workers: int, max_in_flight: int) -> EvidenceAdapterCapability:
    if not isinstance(adapter, EvidenceAdapter):
        raise EvidenceAdapterContractError("adapter does not implement EvidenceAdapter")
    try:
        capability = adapter.capability
    except Exception:
        raise EvidenceAdapterContractError("adapter capability could not be read") from None
    if not isinstance(capability, EvidenceAdapterCapability):
        raise EvidenceAdapterContractError("adapter capability has the wrong type")
    if (
        isinstance(max_in_flight, bool) or not isinstance(max_in_flight, int)
        or not 1 <= max_in_flight <= MAX_ADAPTER_IN_FLIGHT
    ):
        raise EvidenceAdapterBoundError(
            f"max_in_flight must be in 1..{MAX_ADAPTER_IN_FLIGHT}"
        )
    if (
        isinstance(workers, bool) or not isinstance(workers, int)
        or not 1 <= workers <= MAX_ADAPTER_IN_FLIGHT
    ):
        raise EvidenceAdapterBoundError(f"workers must be in 1..{MAX_ADAPTER_IN_FLIGHT}")
    if workers > max_in_flight:
        raise EvidenceAdapterBoundError("workers must not exceed max_in_flight")
    return capability


def _invoke(
    adapter: EvidenceAdapter,
    capability: EvidenceAdapterCapability,
    bundle: EvidenceBundle,
    ordinal: int,
) -> EvidenceAdapterReceipt:
    try:
        result = adapter.publish_bundle(bundle)
    except Exception:
        return EvidenceAdapterReceipt(
            capability.adapter_id,
            capability.adapter_version,
            bundle.bundle_id,
            ordinal,
            EvidenceAdapterReceiptStatus.FAILURE,
            error_code="adapter.operation_failed",
        )
    if not isinstance(result, EvidenceAdapterPublication):
        raise EvidenceAdapterContractError(
            "adapter publish_bundle returned the wrong type"
        )
    return EvidenceAdapterReceipt(
        capability.adapter_id,
        capability.adapter_version,
        bundle.bundle_id,
        ordinal,
        EvidenceAdapterReceiptStatus.SUCCESS,
        external_locator=result.external_locator,
    )


def publish_evidence_bundles(
    adapter: EvidenceAdapter,
    bundles: Iterable[EvidenceBundle],
    *,
    workers: int = 1,
    max_in_flight: int = DEFAULT_ADAPTER_IN_FLIGHT,
    max_receipts_bytes: int = MAX_ADAPTER_RECEIPTS_BYTES,
) -> tuple[EvidenceAdapterReceipt, ...]:
    """Publish caller-ordered bundles through one explicitly supplied adapter.

    Submission uses a sliding bounded window. Completion timing never changes
    returned order. Adapter exceptions become redacted failure receipts; contract
    violations and core orchestration failures remain typed exceptions.
    """
    capability = _validate_options(adapter, workers, max_in_flight)
    if (
        isinstance(max_receipts_bytes, bool) or not isinstance(max_receipts_bytes, int)
        or not 0 <= max_receipts_bytes <= MAX_ADAPTER_RECEIPTS_BYTES
    ):
        raise EvidenceAdapterBoundError(
            f"max_receipts_bytes must be in 0..{MAX_ADAPTER_RECEIPTS_BYTES}"
        )
    try:
        iterator = iter(bundles)
    except TypeError:
        raise EvidenceAdapterContractError("bundles must be an iterable") from None

    executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="evidence-adapter")
    futures: dict[int, Future[EvidenceAdapterReceipt]] = {}
    exhausted = False
    next_ordinal = 0
    receipts: list[EvidenceAdapterReceipt] = []
    aggregate = 0

    def submit_one() -> bool:
        nonlocal exhausted, next_ordinal
        if exhausted:
            return False
        try:
            bundle = next(iterator)
        except StopIteration:
            exhausted = True
            return False
        except Exception:
            raise EvidenceAdapterOrchestrationError("bundle iterable failed") from None
        if not isinstance(bundle, EvidenceBundle):
            raise EvidenceAdapterContractError("bundles must contain EvidenceBundle values")
        ordinal = next_ordinal
        next_ordinal += 1
        futures[ordinal] = executor.submit(_invoke, adapter, capability, bundle, ordinal)
        return True

    try:
        while len(futures) < max_in_flight and submit_one():
            pass
        output_ordinal = 0
        while futures:
            try:
                receipt = futures.pop(output_ordinal).result()
            except EvidenceAdapterError:
                raise
            except Exception:
                raise EvidenceAdapterOrchestrationError(
                    "adapter orchestration failed"
                ) from None
            encoded_size = len(canonical_adapter_receipt_bytes(receipt))
            if aggregate + encoded_size > max_receipts_bytes:
                raise EvidenceAdapterBoundError(
                    f"aggregate adapter receipts exceed the {max_receipts_bytes}-byte limit"
                )
            aggregate += encoded_size
            receipts.append(receipt)
            output_ordinal += 1
            submit_one()
    finally:
        for future in futures.values():
            future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)
    return tuple(receipts)
