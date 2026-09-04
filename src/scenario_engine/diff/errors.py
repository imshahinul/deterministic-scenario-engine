"""Stable Phase 2.6 structured semantic diff errors."""

from scenario_engine.errors import ScenarioEngineError


class DiffError(ScenarioEngineError):
    """Base class for deterministic semantic diff failures."""


class UnsupportedDiffTargetError(DiffError, TypeError):
    """The supplied value is not an authorized inspection or engine target."""


class DiffSchemaError(DiffError, ValueError):
    """A diff model does not satisfy its versioned schema."""


class DiffBoundError(DiffError, ValueError):
    """Diff processing would exceed a finite deterministic bound."""


class DiffModeError(DiffError, ValueError):
    """The requested semantic diff mode is unsupported."""
