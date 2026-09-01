"""Deterministic public errors for the Phase 0.1B declarative layer."""

from scenario_engine.errors import ScenarioEngineError


class DSLError(ScenarioEngineError, ValueError):
    """Base class for declarative scenario errors."""


class DSLParseError(DSLError):
    """The YAML stream could not be safely loaded."""


class DSLSchemaError(DSLError):
    """The loaded document has an invalid shape or value."""


class UnsupportedDSLVersionError(DSLSchemaError):
    """The document requests an unsupported DSL version."""


class DSLCompilationError(DSLError):
    """The document is well-shaped but statically invalid."""
