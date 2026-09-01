"""Small deterministic ecommerce generator reference pack.

The algorithms use only addressed services supplied by
``PluginGenerationContext`` and explicit arguments.  Version ``"1"`` freezes
their current behavior.  Importing this module performs no registration.
"""

from __future__ import annotations

from typing import Any, Mapping

from scenario_engine.plugins import GeneratorPlugin, PluginGenerationContext, PluginRegistry


VERSION = "1"


def _text(arguments: Mapping[str, Any], name: str, default: str) -> str:
    value = arguments.get(name, default)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def customer_email(context: PluginGenerationContext, arguments: Mapping[str, Any]) -> str:
    prefix = _text(arguments, "prefix", "customer").lower()
    domain = _text(arguments, "domain", "example.test").lower()
    token = context.rng.inclusive_int(100000, 999999)
    return f"{prefix}.{token}@{domain}"


def sku(context: PluginGenerationContext, arguments: Mapping[str, Any]) -> str:
    prefix = _text(arguments, "prefix", "SKU").upper()
    token = context.rng.inclusive_int(100000, 999999)
    return f"{prefix}-{token}"


def order_number(context: PluginGenerationContext, arguments: Mapping[str, Any]) -> str:
    prefix = _text(arguments, "prefix", "ORD").upper()
    token = context.ids.derive(context.address, "order-number").value[-12:].upper()
    return f"{prefix}-{token}"


def tracking_number(context: PluginGenerationContext, arguments: Mapping[str, Any]) -> str:
    prefix = _text(arguments, "prefix", "SYN").upper()
    token = context.ids.derive(context.address, "tracking-number").value[-14:].upper()
    return f"{prefix}-{token}"


def ecommerce_registry() -> PluginRegistry:
    """Return a new immutable registry containing the four version-1 plugins."""
    return PluginRegistry((
        GeneratorPlugin("ecommerce.customer_email", VERSION, customer_email),
        GeneratorPlugin("ecommerce.sku", VERSION, sku),
        GeneratorPlugin("ecommerce.order_number", VERSION, order_number),
        GeneratorPlugin("ecommerce.tracking_number", VERSION, tracking_number),
    ))
