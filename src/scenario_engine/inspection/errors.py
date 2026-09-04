"""Stable Phase 2.5 inspection and explanation errors."""

from scenario_engine.errors import ScenarioEngineError


class InspectionError(ScenarioEngineError):
    """Base class for deterministic inspection failures."""


class UnsupportedInspectionTargetError(InspectionError, TypeError):
    """The supplied value is not an authorized inspection target."""


class InspectionSchemaError(InspectionError, ValueError):
    """Inspection evidence does not satisfy the versioned schema."""


class InspectionBoundError(InspectionError, ValueError):
    """Inspection would exceed a finite deterministic bound."""


class ExplanationError(InspectionError):
    """Base class for explanation-specific failures."""


class RedactionConfigurationError(InspectionError, ValueError):
    """A redaction configuration is malformed."""
