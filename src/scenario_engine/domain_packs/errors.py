"""Stable errors for the explicit declarative domain-pack boundary."""

from scenario_engine.errors import ScenarioEngineError


class DomainPackError(ScenarioEngineError, ValueError):
    """Base class for domain-pack diagnostics."""


class DomainPackDefinitionError(DomainPackError):
    """A pack, coordinate, or registry definition is invalid."""


class DomainPackNotFoundError(DomainPackError):
    """An explicitly requested exact coordinate is absent."""


class DomainPackCollisionError(DomainPackError):
    """More than one pack claims the same name or coordinate."""


class DomainPackBoundError(DomainPackDefinitionError):
    """A finite domain-pack safety bound was exceeded."""
