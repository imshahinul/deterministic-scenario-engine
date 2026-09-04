"""Public Phase 2.2 deterministic local composition API."""

from .canonical import canonical_composition_bytes, composed_suite_hash, module_content_hash
from .errors import (
    CompositionBoundError,
    CompositionDeclarationError,
    CompositionError,
    CompositionParseError,
    CompositionPathError,
    CompositionRootEscapeError,
    CompositionSuiteContractError,
    CompositionSymlinkError,
    DuplicateModuleAliasError,
    ModuleFileTypeError,
    ModuleNotFoundError,
    ModuleParseError,
    NamespaceCollisionError,
    NestedCompositionError,
    UnsupportedCompositionSourceError,
)
from .models import (
    COMPOSITION_CONTRACT_VERSION,
    MAX_AGGREGATE_INPUT_BYTES,
    MAX_CANONICAL_COMPOSED_BYTES,
    MAX_MODULE_DOCUMENT_BYTES,
    MAX_MODULES,
    MAX_ROOT_DOCUMENT_BYTES,
    ComposedExecution,
    ComposedSuite,
    ModuleIdentity,
)
from .resolver import load_composed_suite
from .runtime import execute_composed_suite


__all__ = (
    "COMPOSITION_CONTRACT_VERSION",
    "MAX_AGGREGATE_INPUT_BYTES",
    "MAX_CANONICAL_COMPOSED_BYTES",
    "MAX_MODULE_DOCUMENT_BYTES",
    "MAX_MODULES",
    "MAX_ROOT_DOCUMENT_BYTES",
    "ComposedExecution",
    "ComposedSuite",
    "CompositionBoundError",
    "CompositionDeclarationError",
    "CompositionError",
    "CompositionParseError",
    "CompositionPathError",
    "CompositionRootEscapeError",
    "CompositionSuiteContractError",
    "CompositionSymlinkError",
    "DuplicateModuleAliasError",
    "ModuleFileTypeError",
    "ModuleIdentity",
    "ModuleNotFoundError",
    "ModuleParseError",
    "NamespaceCollisionError",
    "NestedCompositionError",
    "UnsupportedCompositionSourceError",
    "canonical_composition_bytes",
    "composed_suite_hash",
    "execute_composed_suite",
    "load_composed_suite",
    "module_content_hash",
)
