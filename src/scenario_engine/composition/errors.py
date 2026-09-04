"""Deterministic errors for secure local scenario composition."""

from __future__ import annotations

from scenario_engine.suite import SuiteContractError


class CompositionError(SuiteContractError):
    """Base class for Phase 2.2 composition failures."""

    code = "composition.invalid"


class CompositionDeclarationError(CompositionError):
    code = "composition.declaration_invalid"


class DuplicateModuleAliasError(CompositionDeclarationError):
    code = "composition.alias_duplicate"


class NestedCompositionError(CompositionDeclarationError):
    code = "composition.nested_forbidden"


class CompositionPathError(CompositionError):
    code = "composition.path_invalid"


class CompositionRootEscapeError(CompositionPathError):
    code = "composition.root_escape"


class CompositionSymlinkError(CompositionPathError):
    code = "composition.symlink_forbidden"


class ModuleNotFoundError(CompositionPathError):
    code = "composition.module_missing"


class ModuleFileTypeError(CompositionPathError):
    code = "composition.module_not_regular"


class UnsupportedCompositionSourceError(CompositionPathError):
    code = "composition.source_unsupported"


class CompositionParseError(CompositionError):
    code = "composition.yaml_invalid"


class ModuleParseError(CompositionParseError):
    code = "composition.module_parse_invalid"


class NamespaceCollisionError(CompositionError):
    code = "composition.namespace_collision"


class CompositionBoundError(CompositionError):
    code = "composition.bound_exceeded"


class CompositionSuiteContractError(CompositionError):
    code = "composition.suite_contract_mismatch"
