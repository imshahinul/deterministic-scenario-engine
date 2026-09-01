"""Deliberately small supported Python API for Deterministic Scenario Engine."""

from .address import ExecutionAddress
from .canonical import (
    canonical_scenario_bytes, canonical_scenario_hash, canonical_scenario_payload,
)
from .control_flow import ControlFlowError
from .dsl import (
    DSLCompilationError, DSLError, DSLParseError, DSLSchemaError,
    compile_document, evaluate_scenario, parse_yaml, parse_yaml_file,
    replay_scenario, run_scenario,
)
from .errors import ScenarioEngineError
from .expressions import ExpressionEvaluationError
from .faults import FaultError
from .ids import LogicalID
from .invariants import InvariantError
from .manifest import (
    ENGINE_VERSION, ReplayCompatibilityError, ReproducibilityManifest,
)
from .oracle import OracleError
from .plugins import (
    GeneratorPlugin, PluginError, PluginGenerationContext, PluginRegistry,
)
from .resources import ResourceError
from .result import ScenarioResult
from .validation import ConstraintError, ResourceValidationError
from .values import MISSING

__all__ = [
    "ENGINE_VERSION", "MISSING", "LogicalID", "ExecutionAddress",
    "ScenarioResult", "ReproducibilityManifest", "parse_yaml",
    "parse_yaml_file", "compile_document", "run_scenario", "replay_scenario",
    "evaluate_scenario", "canonical_scenario_payload", "canonical_scenario_bytes",
    "canonical_scenario_hash", "GeneratorPlugin", "PluginRegistry",
    "PluginGenerationContext", "ScenarioEngineError", "DSLError",
    "DSLParseError", "DSLSchemaError", "DSLCompilationError",
    "ExpressionEvaluationError", "ResourceError", "ResourceValidationError",
    "ConstraintError", "ControlFlowError", "InvariantError", "FaultError",
    "OracleError", "ReplayCompatibilityError", "PluginError",
]
