"""Stable Phase 2.9 oracle assertion errors."""

from scenario_engine.errors import ScenarioEngineError


class OracleAssertionError(ScenarioEngineError):
    """Base error for deterministic post-result assertions."""


class OracleAssertionSchemaError(OracleAssertionError):
    """An assertion declaration is malformed."""


class OracleAssertionBoundError(OracleAssertionError):
    """A deterministic assertion bound was exceeded."""


class UnsupportedOracleAssertionError(OracleAssertionError):
    """The requested assertion kind is not supported."""


class OracleAssertionTargetError(OracleAssertionError):
    """The supplied recorded-evidence target is unsupported."""
