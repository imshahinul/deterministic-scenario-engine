"""Public Phase 2.3 deterministic scenario-matrix API."""

from .canonical import MATRIX_PLAN_CONTRACT_VERSION, canonical_matrix_bytes, stable_case_id
from .errors import (
    DuplicateMatrixCaseError, MatrixCardinalityError, MatrixCaseIdentityError,
    MatrixCaseNotFoundError, MatrixDeclarationError, MatrixDimensionError,
    MatrixError, MatrixFilterError, UnsupportedParameterBindingError,
)
from .expand import expand_matrix, raw_cardinality, select_matrix_case
from .filtering import evaluate_filter
from .models import (
    MAX_DIMENSIONS, MAX_RAW_CARDINALITY, MAX_RETAINED_CASES,
    MAX_VALUES_PER_DIMENSION, MatrixDimension, MatrixExecution, MatrixPlan,
)
from .runtime import execute_matrix, execute_matrix_case


__all__ = (
    "DuplicateMatrixCaseError", "MATRIX_PLAN_CONTRACT_VERSION", "MAX_DIMENSIONS",
    "MAX_RAW_CARDINALITY", "MAX_RETAINED_CASES", "MAX_VALUES_PER_DIMENSION",
    "MatrixCardinalityError", "MatrixCaseIdentityError", "MatrixCaseNotFoundError",
    "MatrixDeclarationError", "MatrixDimension", "MatrixDimensionError", "MatrixError",
    "MatrixExecution", "MatrixFilterError", "MatrixPlan", "UnsupportedParameterBindingError",
    "canonical_matrix_bytes", "evaluate_filter", "execute_matrix", "execute_matrix_case",
    "expand_matrix", "raw_cardinality", "select_matrix_case", "stable_case_id",
)
