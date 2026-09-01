"""Stable public exception root for Scenario Engine-owned failures."""


class ScenarioEngineError(Exception):
    """Root of all intended user-facing Scenario Engine exceptions."""


class OptionalDependencyError(ScenarioEngineError, ImportError):
    """An explicitly imported optional integration is not installed."""


class PytestIntegrationError(OptionalDependencyError):
    """The optional pytest integration cannot be loaded."""
