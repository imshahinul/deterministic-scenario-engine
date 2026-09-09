"""Public Phase 2.9 deterministic post-result assertion contract."""

from .errors import (
    OracleAssertionBoundError, OracleAssertionError, OracleAssertionSchemaError,
    OracleAssertionTargetError, UnsupportedOracleAssertionError,
)
from .evaluate import evaluate, evaluate_assertions
from .models import (
    MAX_ASSERTIONS, MAX_ASSERTION_BYTES, MAX_ASSERTION_PATH_DEPTH, MAX_ASSERTION_SCAN_RECORDS,
    ORACLE_ASSERTION_SCHEMA_VERSION, ORACLE_EVALUATION_SCHEMA_VERSION, OracleAssertion,
    OracleAssertionEvaluation, OracleAssertionKind, OracleAssertionOutcome, OracleAssertionResult,
)
from .serialization import (
    assertion_to_jsonable, assertions_to_jsonable, canonical_assertion_bytes,
    canonical_assertion_text, canonical_evaluation_bytes, canonical_evaluation_text,
    evaluation_to_jsonable,
)


__all__ = (
    "MAX_ASSERTIONS", "MAX_ASSERTION_BYTES", "MAX_ASSERTION_PATH_DEPTH", "MAX_ASSERTION_SCAN_RECORDS",
    "ORACLE_ASSERTION_SCHEMA_VERSION", "ORACLE_EVALUATION_SCHEMA_VERSION", "OracleAssertion",
    "OracleAssertionBoundError", "OracleAssertionError", "OracleAssertionEvaluation", "OracleAssertionKind",
    "OracleAssertionOutcome", "OracleAssertionResult", "OracleAssertionSchemaError", "OracleAssertionTargetError",
    "UnsupportedOracleAssertionError", "assertion_to_jsonable", "assertions_to_jsonable",
    "canonical_assertion_bytes", "canonical_assertion_text", "canonical_evaluation_bytes",
    "canonical_evaluation_text", "evaluate", "evaluate_assertions", "evaluation_to_jsonable",
)
