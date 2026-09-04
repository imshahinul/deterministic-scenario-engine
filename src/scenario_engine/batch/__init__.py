"""Public Phase 2.4 deterministic batch-execution API."""

from scenario_engine.suite import (
    BATCH_CONTRACT_VERSION, BATCH_SCHEMA_VERSION, BatchItemResult,
    BatchManifest, BatchResultEnvelope, BatchStatus, FailureRecord,
)

from .canonical import BATCH_PLAN_IDENTITY_VERSION, canonical_batch_bytes
from .errors import (
    BatchBoundError, BatchError, BatchIdentityMismatchError, BatchPlanError,
    BatchResultBoundError, BatchSizeBoundError, DuplicateRunIdentityError,
    InvalidExecutionOptionError, InvalidStreamingBoundError,
    InvalidWorkerCountError, UnsupportedBatchItemError,
)
from .models import (
    DEFAULT_RETAINED_RESULT_BYTES, MAX_BATCH_ITEMS, MAX_IN_FLIGHT, MAX_WORKERS,
    BatchExecution, BatchExecutionItem, BatchPlan, ExecutionMode, RunRequest,
)
from .runtime import OrderedBatchStream, execute_batch, stream_batch


__all__ = (
    "BATCH_CONTRACT_VERSION", "BATCH_PLAN_IDENTITY_VERSION", "BATCH_SCHEMA_VERSION",
    "DEFAULT_RETAINED_RESULT_BYTES", "MAX_BATCH_ITEMS", "MAX_IN_FLIGHT", "MAX_WORKERS",
    "BatchBoundError", "BatchError", "BatchExecution", "BatchExecutionItem",
    "BatchIdentityMismatchError", "BatchItemResult", "BatchManifest", "BatchPlan",
    "BatchPlanError", "BatchResultBoundError", "BatchResultEnvelope", "BatchSizeBoundError",
    "BatchStatus", "DuplicateRunIdentityError", "ExecutionMode", "FailureRecord",
    "InvalidExecutionOptionError", "InvalidStreamingBoundError", "InvalidWorkerCountError",
    "OrderedBatchStream", "RunRequest", "UnsupportedBatchItemError",
    "canonical_batch_bytes", "execute_batch", "stream_batch",
)
