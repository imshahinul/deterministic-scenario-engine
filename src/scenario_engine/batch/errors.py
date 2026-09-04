"""Stable errors for deterministic batch planning and execution."""

from scenario_engine.suite import SuiteContractError


class BatchError(SuiteContractError):
    """Base class for Phase 2.4 batch failures."""

    code = "batch.error"


class BatchPlanError(BatchError):
    """A batch declaration or immutable plan is invalid."""

    code = "batch.plan_invalid"


class DuplicateRunIdentityError(BatchPlanError):
    """Two plan positions use the same batch run coordinate."""

    code = "batch.run_identity_duplicate"


class UnsupportedBatchItemError(BatchPlanError):
    """A request does not identify a supported accepted engine operation."""

    code = "batch.item_unsupported"


class BatchBoundError(BatchError):
    """A finite batch execution bound was exceeded."""

    code = "batch.bound_exceeded"


class BatchSizeBoundError(BatchBoundError):
    code = "batch.size_exceeded"


class BatchResultBoundError(BatchBoundError):
    code = "batch.result_bytes_exceeded"


class InvalidWorkerCountError(BatchPlanError):
    code = "batch.worker_count_invalid"


class InvalidStreamingBoundError(BatchPlanError):
    code = "batch.streaming_bound_invalid"


class InvalidExecutionOptionError(BatchPlanError):
    code = "batch.execution_option_invalid"


class BatchIdentityMismatchError(BatchPlanError):
    code = "batch.identity_mismatch"
