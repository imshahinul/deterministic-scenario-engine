"""Phase 0.1B minimal, strictly validated linear declarative DSL."""

from .compiler import compile_document
from .errors import (
    DSLCompilationError, DSLError, DSLParseError, DSLSchemaError,
    UnsupportedDSLVersionError,
)
from .models import CompiledScenario, ScenarioDocument
from .parser import decode_semantic_value, parse_yaml, parse_yaml_file
from .runtime import ScenarioResult, replay_scenario, run_scenario
from scenario_engine.resources import ResourceCycleError, ResourceResolutionError, ResolvedResources, resolve_resources
from scenario_engine.validation import ConstraintDefinitionError, ConstraintViolation, ResourceValidationError

__all__ = [
    "CompiledScenario", "DSLCompilationError", "DSLError", "DSLParseError",
    "DSLSchemaError", "ScenarioDocument", "ScenarioResult",
    "UnsupportedDSLVersionError", "compile_document", "decode_semantic_value",
    "parse_yaml", "parse_yaml_file", "replay_scenario", "run_scenario",
    "ResourceCycleError", "ResourceResolutionError", "ResolvedResources", "resolve_resources",
    "ConstraintDefinitionError", "ConstraintViolation", "ResourceValidationError",
]
