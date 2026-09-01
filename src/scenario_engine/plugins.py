"""Explicit deterministic generator-plugin boundary.

Plugins are trusted Python callables, not sandboxed code.  The contract forbids
wall-clock time, global randomness, environment/process state, filesystem and
network access.  Deterministic services are supplied only by
``PluginGenerationContext`` and inputs arrive as isolated semantic arguments.
There is deliberately no global registry or dynamic discovery mechanism.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping

from .address import ExecutionAddress
from .clock import LogicalClock
from .context import GenerationContext
from .ids import DeterministicIDProvider
from .rng import DeterministicRNG
from .values import MISSING, normalize


_PLUGIN_NAME = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")


class PluginError(ValueError):
    """Base class for stable plugin-boundary diagnostics."""


class PluginDefinitionError(PluginError):
    """A plugin or registry definition is invalid."""


class PluginNotFoundError(PluginError):
    """An explicitly required plugin is absent."""


class PluginVersionMismatchError(PluginError):
    """A registry plugin does not match its declared algorithm version."""


class PluginCompatibilityError(PluginError):
    """A plugin scenario cannot execute or replay with a supplied registry."""


class PluginExecutionError(RuntimeError):
    """A plugin callable raised an unexpected exception."""


class PluginResultError(TypeError):
    """A plugin returned a value outside the engine semantic model."""


@dataclass(frozen=True, slots=True)
class PluginGenerationContext:
    """Addressed deterministic services exposed to a generator plugin."""

    rng: DeterministicRNG
    clock: LogicalClock
    ids: DeterministicIDProvider
    address: ExecutionAddress

    @classmethod
    def from_generation_context(cls, context: GenerationContext) -> PluginGenerationContext:
        return cls(context.rng(), context.clock, context.ids, context.address)


PluginCallable = Callable[[PluginGenerationContext, Mapping[str, Any]], Any]


@dataclass(frozen=True, slots=True)
class GeneratorPlugin:
    """A named, explicitly versioned deterministic generator algorithm."""

    name: str
    version: str
    generate: PluginCallable

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not _PLUGIN_NAME.fullmatch(self.name):
            raise PluginDefinitionError(
                "plugin name must be lowercase namespaced ASCII components"
            )
        if not isinstance(self.version, str) or not self.version.strip():
            raise PluginDefinitionError("plugin version must be a non-empty string")
        if self.version != self.version.strip():
            raise PluginDefinitionError("plugin version must not contain surrounding whitespace")
        if not callable(self.generate):
            raise PluginDefinitionError("plugin generate must be callable")


class PluginRegistry:
    """Immutable explicit plugin registry; iterable order has no semantics."""

    __slots__ = ("_plugins",)

    def __init__(self, plugins: Iterable[GeneratorPlugin] = ()) -> None:
        collected: dict[str, GeneratorPlugin] = {}
        for plugin in plugins:
            if not isinstance(plugin, GeneratorPlugin):
                raise PluginDefinitionError("registry entries must be GeneratorPlugin objects")
            if plugin.name in collected:
                raise PluginDefinitionError(f"duplicate plugin name: {plugin.name}")
            collected[plugin.name] = plugin
        self._plugins = MappingProxyType({name: collected[name] for name in sorted(collected)})

    def get(self, name: str) -> GeneratorPlugin:
        try:
            return self._plugins[name]
        except KeyError:
            raise PluginNotFoundError(f"plugin not found: {name}") from None

    def require(self, name: str, version: str) -> GeneratorPlugin:
        plugin = self.get(name)
        if plugin.version != version:
            raise PluginVersionMismatchError(
                f"plugin version mismatch: {name} requires {version}, registry has {plugin.version}"
            )
        return plugin

    def __len__(self) -> int:
        return len(self._plugins)

    def __iter__(self):
        return iter(self._plugins.values())


EMPTY_PLUGIN_REGISTRY = PluginRegistry()


def isolate_arguments(value: Any) -> Any:
    """Create an immutable recursive snapshot of a semantic argument value."""
    if value is MISSING or value is None or isinstance(value, (str, bool, int)):
        return value
    # Decimal, datetime, timedelta and LogicalID are immutable semantic atoms.
    if type(value).__module__ in {"decimal", "datetime", "scenario_engine.ids"}:
        normalize(value)
        return value
    if isinstance(value, (list, tuple)):
        return tuple(isolate_arguments(item) for item in value)
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise PluginResultError("plugin arguments require string mapping keys")
        return MappingProxyType({key: isolate_arguments(value[key]) for key in sorted(value)})
    raise PluginResultError(f"unsupported plugin argument value: {type(value).__name__}")


def invoke_plugin(
    plugin: GeneratorPlugin,
    context: GenerationContext,
    arguments: Mapping[str, Any],
) -> Any:
    """Invoke a plugin with stable errors and semantic-result validation."""
    plugin_context = PluginGenerationContext.from_generation_context(context)
    isolated = isolate_arguments(arguments)
    try:
        result = plugin.generate(plugin_context, isolated)
    except Exception as error:
        if isinstance(error, (PluginError, PluginResultError)):
            raise
        raise PluginExecutionError(
            f"plugin {plugin.name}@{plugin.version} failed at "
            f"{context.address.canonical()}: {type(error).__name__}"
        ) from error
    try:
        normalize(result)
    except (TypeError, ValueError) as error:
        raise PluginResultError(
            f"plugin {plugin.name}@{plugin.version} returned unsupported semantic value: "
            f"{type(result).__name__}"
        ) from error
    return result
