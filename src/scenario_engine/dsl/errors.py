"""Deterministic public errors for the Phase 0.1B declarative layer."""

from scenario_engine.diagnostics import HumanDiagnostic
from scenario_engine.errors import ScenarioEngineError


class DSLError(ScenarioEngineError, ValueError):
    """Base class for declarative scenario errors."""

    diagnostic_code = "DSL_SEMANTIC_ERROR"
    diagnostic_category = "DSL_SEMANTIC"

    def __init__(
        self,
        message: str,
        *,
        semantic_path: str | None = None,
        expected: str | None = None,
        received: str | None = None,
        remediation: str | None = None,
        diagnostic_message: str | None = None,
    ) -> None:
        self.human_diagnostic = HumanDiagnostic(
            self.diagnostic_code, self.diagnostic_category, diagnostic_message or message,
            semantic_path, expected, received, remediation,
        )
        super().__init__(message)


class DSLParseError(DSLError):
    """The YAML stream could not be safely loaded."""

    diagnostic_code = "DSL_PARSE_ERROR"
    diagnostic_category = "DSL_SCHEMA"


class DSLSchemaError(DSLError):
    """The loaded document has an invalid shape or value."""

    diagnostic_code = "DSL_SCHEMA_ERROR"
    diagnostic_category = "DSL_SCHEMA"


class UnsupportedDSLVersionError(DSLSchemaError):
    """The document requests an unsupported DSL version."""


class DSLCompilationError(DSLError):
    """The document is well-shaped but statically invalid."""

    diagnostic_code = "DSL_SEMANTIC_ERROR"
    diagnostic_category = "DSL_SEMANTIC"
