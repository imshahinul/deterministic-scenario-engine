"""Single deterministic batch orchestration path for complete and streamed use."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import hashlib
import json
import re
from typing import Iterator, Mapping

from scenario_engine.composition import execute_composed_suite
from scenario_engine.dsl import run_scenario
from scenario_engine.errors import ScenarioEngineError
from scenario_engine.matrix import execute_matrix_case
from scenario_engine.suite import (
    ArtifactReference, BatchItemResult, BatchManifest, BatchResultEnvelope,
    BatchStatus, FailureRecord, canonical_suite_bytes,
)

from .canonical import canonical_hash
from .errors import (
    BatchIdentityMismatchError, BatchResultBoundError,
    InvalidExecutionOptionError, InvalidStreamingBoundError,
    InvalidWorkerCountError,
)
from .models import (
    MAX_IN_FLIGHT, MAX_WORKERS, BatchExecution, BatchExecutionItem, BatchPlan,
    ExecutionMode, RunRequest,
)


def _thaw(value):
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _manifest_bytes(result) -> bytes:
    return json.dumps(
        result.manifest.normalized(), ensure_ascii=False, allow_nan=False,
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _stable_failure(error: Exception) -> FailureRecord:
    if isinstance(error, ScenarioEngineError):
        family = type(error).__name__
        code = getattr(type(error), "code", None)
        if not isinstance(code, str) or not code:
            words = re.sub(r"(?<!^)(?=[A-Z])", "_", family).lower()
            code = "engine." + words.removesuffix("_error")
        return FailureRecord(family, code, f"{family} occurred")
    return FailureRecord(
        "InternalExecutionError", "batch.item_internal",
        "batch item execution failed",
    )


def _execute(request: RunRequest) -> BatchExecutionItem:
    try:
        inputs = _thaw(request.inputs)
        if request.execution_mode is ExecutionMode.DIRECT:
            result = run_scenario(
                request.target, request.root_seed, run_index=request.run_index,
                locale=request.locale, inputs=inputs, plugins=request.plugins,
            )
            manifest_bytes = _manifest_bytes(result)
        elif request.execution_mode is ExecutionMode.COMPOSED:
            composed = execute_composed_suite(
                request.target, request.root_seed, run_index=request.run_index,
                locale=request.locale, inputs=inputs, plugins=request.plugins,
            )
            result = composed.result
            manifest_bytes = canonical_suite_bytes(composed.run_manifest)
        else:
            result = execute_matrix_case(
                request.target, request.matrix_case, inputs=inputs,
                plugins=request.plugins,
            )
            manifest_bytes = _manifest_bytes(result)
        result_bytes = result.to_json_bytes()
        manifest_ref = ArtifactReference(
            "run_manifest", request.child_identity,
            hashlib.sha256(manifest_bytes).hexdigest(),
        )
        result_ref = ArtifactReference(
            "scenario_result", request.child_identity,
            hashlib.sha256(result_bytes).hexdigest(),
        )
        record = BatchItemResult(
            request.run_id, request.child_identity, BatchStatus.SUCCESS,
            manifest_ref, result_ref,
        )
        return BatchExecutionItem(
            request, record, result, len(manifest_bytes) + len(result_bytes),
        )
    except Exception as error:
        failure = _stable_failure(error)
        record = BatchItemResult(
            request.run_id, request.child_identity, BatchStatus.FAILURE,
            failure=failure,
        )
        return BatchExecutionItem(
            request, record, retained_bytes=len(canonical_suite_bytes(failure)),
        )


def _not_run(request: RunRequest) -> BatchExecutionItem:
    return BatchExecutionItem(
        request,
        BatchItemResult(request.run_id, request.child_identity, BatchStatus.NOT_RUN),
    )


def _envelope(plan: BatchPlan, records: tuple[BatchItemResult, ...]) -> BatchResultEnvelope:
    status_payload = [{
        "child_identity": item.child_identity,
        "child_manifest_hash": item.child_manifest.sha256 if item.child_manifest else None,
        "child_result_hash": item.child_result.sha256 if item.child_result else None,
        "failure_code": item.failure.code if item.failure else None,
        "run_identity": item.run_identity,
        "status": item.status.value,
    } for item in records]
    bundle_hash = canonical_hash({"items": status_payload, "plan_hash": plan.plan_hash})
    manifest = BatchManifest(
        plan_identity=plan.plan_identity,
        plan_hash=plan.plan_hash,
        bundle_identity="batch-bundle:" + bundle_hash,
        items=records,
        success_count=sum(item.status is BatchStatus.SUCCESS for item in records),
        failure_count=sum(item.status is BatchStatus.FAILURE for item in records),
        not_run_count=sum(item.status is BatchStatus.NOT_RUN for item in records),
    )
    envelope = BatchResultEnvelope(manifest)
    canonical_suite_bytes(envelope)
    return envelope


class OrderedBatchStream(Iterator[BatchExecutionItem]):
    """Finite plan-ordered iterator with an explicit bounded in-flight window."""

    def __init__(self, plan: BatchPlan, workers: int, max_in_flight: int) -> None:
        self.plan = plan
        self.workers = workers
        self.max_in_flight = max_in_flight
        self._iterator = self._run()
        self._records: list[BatchItemResult] = []
        self._envelope: BatchResultEnvelope | None = None

    def __iter__(self) -> OrderedBatchStream:
        return self

    def __next__(self) -> BatchExecutionItem:
        try:
            item = next(self._iterator)
        except StopIteration:
            if self._envelope is None:
                self._envelope = _envelope(self.plan, tuple(self._records))
            raise
        self._records.append(item.record)
        return item

    @property
    def envelope(self) -> BatchResultEnvelope:
        if self._envelope is None:
            raise InvalidExecutionOptionError("stream must be exhausted before envelope access")
        return self._envelope

    def _checked(self, item: BatchExecutionItem) -> BatchExecutionItem:
        if item.retained_bytes > self.plan.retained_result_bytes:
            raise BatchResultBoundError(
                f"batch item exceeds retained-result bound {self.plan.retained_result_bytes}"
            )
        return item

    def _run(self):
        if self.plan.fail_fast:
            failed = False
            for request in self.plan.items:
                item = _not_run(request) if failed else self._checked(_execute(request))
                yield item
                failed = failed or item.record.status is BatchStatus.FAILURE
            return
        if not self.plan.items:
            return
        window = min(self.max_in_flight, len(self.plan.items))
        executor = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="scenario-batch")
        futures: dict[int, Future[BatchExecutionItem]] = {}
        submit_position = 0
        try:
            while submit_position < window:
                futures[submit_position] = executor.submit(_execute, self.plan.items[submit_position])
                submit_position += 1
            for position in range(len(self.plan.items)):
                item = self._checked(futures.pop(position).result())
                yield item
                if submit_position < len(self.plan.items):
                    futures[submit_position] = executor.submit(_execute, self.plan.items[submit_position])
                    submit_position += 1
        finally:
            for future in futures.values():
                future.cancel()
            executor.shutdown(wait=True, cancel_futures=True)


def stream_batch(
    plan: BatchPlan, *, workers: int = 1, max_in_flight: int = MAX_IN_FLIGHT,
) -> OrderedBatchStream:
    """Execute through the shared finite plan-ordered bounded stream."""
    _validate_options(plan, workers, max_in_flight)
    return OrderedBatchStream(plan, workers, max_in_flight)


def execute_batch(
    plan: BatchPlan, *, workers: int = 1, max_in_flight: int = MAX_IN_FLIGHT,
) -> BatchExecution:
    """Materialize ordered results from the same bounded streaming engine."""
    stream = stream_batch(plan, workers=workers, max_in_flight=max_in_flight)
    items: list[BatchExecutionItem] = []
    retained = 0
    for item in stream:
        retained += item.retained_bytes
        if retained > plan.retained_result_bytes:
            raise BatchResultBoundError(
                f"batch exceeds retained-result bound {plan.retained_result_bytes}"
            )
        items.append(item)
    if stream.envelope.manifest.plan_hash != plan.plan_hash:
        raise BatchIdentityMismatchError("batch result plan identity mismatch")
    return BatchExecution(plan, tuple(items), stream.envelope)


def _validate_options(plan: BatchPlan, workers: int, max_in_flight: int) -> None:
    if not isinstance(plan, BatchPlan):
        raise TypeError("plan must be a BatchPlan")
    if isinstance(workers, bool) or not isinstance(workers, int) or not 1 <= workers <= MAX_WORKERS:
        raise InvalidWorkerCountError(f"workers must be in 1..{MAX_WORKERS}")
    if plan.fail_fast and workers != 1:
        raise InvalidExecutionOptionError("fail_fast requires exactly one worker")
    if (
        isinstance(max_in_flight, bool) or not isinstance(max_in_flight, int)
        or not 1 <= max_in_flight <= MAX_IN_FLIGHT
    ):
        raise InvalidStreamingBoundError(f"max_in_flight must be in 1..{MAX_IN_FLIGHT}")
    if max_in_flight < workers:
        raise InvalidStreamingBoundError("max_in_flight must be at least workers")
