"""Stable error families for deterministic matrix planning and execution."""

from scenario_engine.errors import ScenarioEngineError


class MatrixError(ScenarioEngineError):
    """Base class for Phase 2.3 matrix errors."""


class MatrixDeclarationError(MatrixError, ValueError):
    """A matrix declaration is invalid."""


class MatrixDimensionError(MatrixDeclarationError):
    """A matrix dimension is invalid or duplicated."""


class MatrixCardinalityError(MatrixError):
    """A pre-filter or retained matrix bound was exceeded."""


class MatrixFilterError(MatrixDeclarationError):
    """A restricted pure filter is invalid or cannot be evaluated."""


class DuplicateMatrixCaseError(MatrixDeclarationError):
    """Two Cartesian positions have the same canonical assignment."""


class MatrixCaseNotFoundError(MatrixError, LookupError):
    """No retained case has the requested stable identity."""


class MatrixCaseIdentityError(MatrixError):
    """A case does not match the plan from which it claims to originate."""


class UnsupportedParameterBindingError(MatrixError):
    """A parameter assignment conflicts with an explicit caller input."""
