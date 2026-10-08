"""Phase 0.1B minimal, strictly validated linear declarative DSL."""

from .compiler import compile_document
from .errors import (
    DSLCompilationError, DSLError, DSLParseError, DSLResourceLimitError, DSLSchemaError,
    UnsupportedDSL2ExecutionError, UnsupportedDSLVersionError,
)
from .models import ActorDocument, CompiledScenario, CompiledScenarioV2, ScenarioDocument, ScenarioDocumentV2
from .parser import decode_semantic_value, parse_yaml, parse_yaml_file
from .runtime import ScenarioResult, evaluate_scenario, replay_scenario, run_scenario
from scenario_engine.invariants import InvariantDefinitionError, InvariantViolation
from scenario_engine.oracle import OracleEvaluation, OracleMismatchError, OracleReport
from scenario_engine.resources import ResourceCycleError, ResourceResolutionError, ResolvedResources, resolve_resources
from scenario_engine.validation import ConstraintDefinitionError, ConstraintViolation, ResourceValidationError
from scenario_engine.control_flow import (BranchConditionError, ControlFlowError,
    RepeatCountError, RepeatLimitError, SubflowCycleError, UnknownSubflowError)
from scenario_engine.expressions import ScopeResolutionError
from scenario_engine.plugins import PluginCompatibilityError

__all__ = [
    "ActorDocument", "CompiledScenario", "CompiledScenarioV2", "DSLCompilationError", "DSLError", "DSLParseError",
    "DSLResourceLimitError", "DSLSchemaError", "ScenarioDocument", "ScenarioDocumentV2", "ScenarioResult",
    "UnsupportedDSL2ExecutionError",
    "UnsupportedDSLVersionError", "compile_document", "decode_semantic_value",
    "parse_yaml", "parse_yaml_file", "replay_scenario", "run_scenario", "evaluate_scenario",
    "ResourceCycleError", "ResourceResolutionError", "ResolvedResources", "resolve_resources",
    "ConstraintDefinitionError", "ConstraintViolation", "ResourceValidationError",
    "BranchConditionError", "ControlFlowError", "RepeatCountError", "RepeatLimitError",
    "ScopeResolutionError", "SubflowCycleError", "UnknownSubflowError",
    "InvariantDefinitionError", "InvariantViolation", "OracleEvaluation", "OracleMismatchError", "OracleReport",
    "PluginCompatibilityError",
]
