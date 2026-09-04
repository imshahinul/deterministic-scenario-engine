from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil

import pytest

import scenario_engine
from scenario_engine._version import VERSION
from scenario_engine.composition import (
    COMPOSITION_CONTRACT_VERSION,
    MAX_MODULES,
    MAX_MODULE_DOCUMENT_BYTES,
    CompositionBoundError,
    CompositionDeclarationError,
    CompositionParseError,
    CompositionPathError,
    CompositionRootEscapeError,
    CompositionSymlinkError,
    DuplicateModuleAliasError,
    ModuleFileTypeError,
    ModuleNotFoundError,
    ModuleParseError,
    NamespaceCollisionError,
    NestedCompositionError,
    UnsupportedCompositionSourceError,
    canonical_composition_bytes,
    execute_composed_suite,
    load_composed_suite,
)
from scenario_engine.manifest import ReproducibilityManifest
from scenario_engine.suite import canonical_suite_bytes


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _root(modules: str, *, resource: str = "alpha.answer") -> str:
    return f"""dsl_version: 1
scenario: composed
clock:
  start: '2026-01-01T00:00:00Z'
initial_state:
  answer: 0
composition:
  modules:
{modules}
steps:
  - id: apply
    write:
      answer:
        $resource: {resource}
    transition: null
"""


def _module(identity: str, value: str = "42", *, comment: str = "") -> str:
    return f"""{comment}dsl_version: 1
module: {identity}
resources:
  answer: {value}
"""


def _suite(tmp_path: Path, modules: str = "    alpha: modules/alpha.yaml"):
    _write(tmp_path / "root.yaml", _root(modules))
    _write(tmp_path / "modules/alpha.yaml", _module("alpha"))
    return load_composed_suite("root.yaml", composition_root=tmp_path)


def test_basic_one_and_multiple_module_composition_executes_existing_runtime(tmp_path: Path) -> None:
    suite = _suite(tmp_path)
    execution = execute_composed_suite(suite, "seed", run_index=3)
    assert execution.result.final_state == {"answer": 42}
    assert isinstance(execution.result.manifest, ReproducibilityManifest)
    assert execution.result.manifest.run_index == 3
    assert execution.run_manifest.child_manifest is execution.result.manifest
    assert execution.run_manifest.suite_hash == suite.composed_hash

    _write(tmp_path / "root.yaml", _root(
        "    beta: modules/beta.yaml\n    alpha: modules/alpha.yaml",
        resource="beta.answer",
    ))
    _write(tmp_path / "modules/beta.yaml", _module("beta", "7"))
    multiple = load_composed_suite("root.yaml", composition_root=tmp_path)
    assert [item.alias for item in multiple.modules] == ["alpha", "beta"]
    assert execute_composed_suite(multiple, "seed").result.final_state == {"answer": 7}


def test_resolution_execution_and_mapping_order_are_deterministic(tmp_path: Path) -> None:
    first = _suite(tmp_path)
    second = load_composed_suite("root.yaml", composition_root=tmp_path)
    assert first == second
    assert canonical_composition_bytes(first) == canonical_composition_bytes(second)
    assert first.composed_hash == second.composed_hash
    assert execute_composed_suite(first, 99).result.to_json_bytes() == execute_composed_suite(second, 99).result.to_json_bytes()

    _write(tmp_path / "modules/beta.yaml", _module("beta", "7"))
    _write(tmp_path / "root.yaml", _root(
        "    beta: modules/beta.yaml\n    alpha: modules/alpha.yaml",
    ))
    unordered = load_composed_suite("root.yaml", composition_root=tmp_path)
    _write(tmp_path / "root.yaml", _root(
        "    alpha: modules/alpha.yaml\n    beta: modules/beta.yaml",
    ))
    ordered = load_composed_suite("root.yaml", composition_root=tmp_path)
    assert unordered.composed_hash == ordered.composed_hash
    assert canonical_composition_bytes(unordered) == canonical_composition_bytes(ordered)


def test_cross_machine_path_and_permitted_file_relocation_independence(tmp_path: Path) -> None:
    left = tmp_path / "machine-a/checkout"
    right = tmp_path / "other-machine/different-checkout"
    left.mkdir(parents=True)
    first = _suite(left)
    shutil.copytree(left, right)
    second = load_composed_suite("root.yaml", composition_root=right)
    assert first.composed_hash == second.composed_hash
    assert canonical_suite_bytes(first.manifest) == canonical_suite_bytes(second.manifest)
    assert str(left).encode() not in canonical_composition_bytes(first)

    _write(right / "root.yaml", _root("    alpha: relocated/content.yaml"))
    _write(right / "relocated/content.yaml", _module("alpha"))
    relocated = load_composed_suite("root.yaml", composition_root=right)
    assert first.composed_hash == relocated.composed_hash


def test_alias_and_semantic_content_are_identity(tmp_path: Path) -> None:
    first = _suite(tmp_path)
    original_module_hash = first.modules[0].content_hash
    _write(tmp_path / "modules/alpha.yaml", _module("alpha", "43"))
    changed = load_composed_suite("root.yaml", composition_root=tmp_path)
    assert changed.modules[0].content_hash != original_module_hash
    assert changed.composed_hash != first.composed_hash

    _write(tmp_path / "root.yaml", _root("    beta: modules/alpha.yaml", resource="beta.answer"))
    _write(tmp_path / "modules/alpha.yaml", _module("beta", "43"))
    alias_changed = load_composed_suite("root.yaml", composition_root=tmp_path)
    assert alias_changed.modules[0].alias == "beta"
    assert alias_changed.modules[0].content_hash == changed.modules[0].content_hash
    assert alias_changed.composed_hash != changed.composed_hash


def test_yaml_comments_whitespace_and_mapping_order_are_semantically_canonical(tmp_path: Path) -> None:
    _write(tmp_path / "root.yaml", _root("    alpha: modules/alpha.yaml"))
    _write(tmp_path / "modules/alpha.yaml", """# comment
dsl_version: 1
module: alpha
resources:
  answer:
    b: 2
    a: 1
""")
    first = load_composed_suite("root.yaml", composition_root=tmp_path)
    _write(tmp_path / "modules/alpha.yaml", """module: alpha
resources: {answer: {a: 1, b: 2}}
dsl_version: 1
""")
    second = load_composed_suite("root.yaml", composition_root=tmp_path)
    assert first.modules[0].content_hash == second.modules[0].content_hash

    _write(tmp_path / "modules/alpha.yaml", """dsl_version: 1
module: alpha
resources:
  answer: [1, 2]
""")
    sequence_a = load_composed_suite("root.yaml", composition_root=tmp_path)
    _write(tmp_path / "modules/alpha.yaml", """dsl_version: 1
module: alpha
resources:
  answer: [2, 1]
""")
    sequence_b = load_composed_suite("root.yaml", composition_root=tmp_path)
    assert sequence_a.modules[0].content_hash != sequence_b.modules[0].content_hash


def test_namespace_resources_cross_module_refs_and_subflow_calls(tmp_path: Path) -> None:
    _write(tmp_path / "root.yaml", """dsl_version: 1
scenario: namespaces
clock: {start: '2026-01-01T00:00:00Z'}
initial_state: {value: 0}
composition:
  modules:
    beta: beta.yaml
    alpha: alpha.yaml
steps:
  - id: call_alpha
    call: {subflow: alpha.set_value}
    transition: null
""")
    _write(tmp_path / "beta.yaml", """dsl_version: 1
module: beta
resources: {shared: 8}
subflows:
  same:
    steps:
      - id: beta_step
        transition: null
""")
    _write(tmp_path / "alpha.yaml", """dsl_version: 1
module: alpha
resources:
  own: 7
  copied: {$ref: beta.shared}
subflows:
  same:
    steps:
      - id: unused
        transition: null
  set_value:
    steps:
      - id: set
        write:
          value: {$resource: alpha.copied}
        transition: null
""")
    suite = load_composed_suite("root.yaml", composition_root=tmp_path)
    assert "alpha.same" in suite.document.subflows
    assert "beta.same" in suite.document.subflows
    assert execute_composed_suite(suite, "seed").result.final_state == {"value": 8}


def test_root_namespace_collisions_fail_deterministically(tmp_path: Path) -> None:
    _write(tmp_path / "root.yaml", _root("    alpha: alpha.yaml"))
    _write(tmp_path / "alpha.yaml", _module("alpha"))
    text = (tmp_path / "root.yaml").read_text().replace(
        "composition:", "resources:\n  alpha: 1\ncomposition:",
    )
    _write(tmp_path / "root.yaml", text)
    with pytest.raises(NamespaceCollisionError, match="collides"):
        load_composed_suite("root.yaml", composition_root=tmp_path)


def test_depth_one_and_module_content_contract(tmp_path: Path) -> None:
    _write(tmp_path / "root.yaml", _root("    alpha: alpha.yaml"))
    _write(tmp_path / "alpha.yaml", """dsl_version: 1
module: alpha
composition: {modules: {nested: nested.yaml}}
resources: {answer: 1}
""")
    with pytest.raises(NestedCompositionError):
        load_composed_suite("root.yaml", composition_root=tmp_path)
    _write(tmp_path / "alpha.yaml", """dsl_version: 1
module: alpha
steps: []
resources: {answer: 1}
""")
    with pytest.raises(CompositionDeclarationError, match="unknown key"):
        load_composed_suite("root.yaml", composition_root=tmp_path)
    _write(tmp_path / "alpha.yaml", _module("different"))
    with pytest.raises(CompositionDeclarationError, match="equal its composition alias"):
        load_composed_suite("root.yaml", composition_root=tmp_path)


@pytest.mark.parametrize("source,error", [
    ("/tmp/module.yaml", CompositionRootEscapeError),
    ("../module.yaml", CompositionRootEscapeError),
    ("modules/../module.yaml", CompositionRootEscapeError),
    ("modules//module.yaml", CompositionRootEscapeError),
    ("modules\\module.yaml", CompositionPathError),
    ("https://example.invalid/module.yaml", UnsupportedCompositionSourceError),
    ("ftp://example.invalid/module.yaml", UnsupportedCompositionSourceError),
    ("file://module.yaml", UnsupportedCompositionSourceError),
    ("git+https://example.invalid/repo", UnsupportedCompositionSourceError),
])
def test_path_and_network_sources_fail_closed(tmp_path: Path, source: str, error: type[Exception]) -> None:
    _write(tmp_path / "root.yaml", _root(f"    alpha: {source}"))
    with pytest.raises(error):
        load_composed_suite("root.yaml", composition_root=tmp_path)


def test_missing_directory_and_symlink_targets_fail_closed(tmp_path: Path) -> None:
    _write(tmp_path / "root.yaml", _root("    alpha: missing.yaml"))
    with pytest.raises(ModuleNotFoundError):
        load_composed_suite("root.yaml", composition_root=tmp_path)
    (tmp_path / "directory.yaml").mkdir()
    _write(tmp_path / "root.yaml", _root("    alpha: directory.yaml"))
    with pytest.raises(ModuleFileTypeError):
        load_composed_suite("root.yaml", composition_root=tmp_path)

    outside = tmp_path.parent / f"{tmp_path.name}-outside.yaml"
    _write(outside, _module("alpha"))
    try:
        os.symlink(outside, tmp_path / "link.yaml")
        _write(tmp_path / "root.yaml", _root("    alpha: link.yaml"))
        with pytest.raises(CompositionSymlinkError):
            load_composed_suite("root.yaml", composition_root=tmp_path)
    finally:
        outside.unlink(missing_ok=True)


@pytest.mark.parametrize("fragment,error", [
    ("composition:\n  modules:\n    alpha: a.yaml\n    alpha: b.yaml", DuplicateModuleAliasError),
    ("composition: &c\n  modules: {alpha: a.yaml}\nother: *c", CompositionParseError),
    ("defaults: &d {alpha: a.yaml}\ncomposition:\n  modules:\n    <<: *d", CompositionParseError),
    ("composition:\n  modules: !custom {alpha: a.yaml}", CompositionParseError),
    ("composition:\n  modules:\n    1: a.yaml", CompositionParseError),
    ("composition:\n  modules:\n    Bad-Alias: a.yaml", CompositionDeclarationError),
    ("composition:\n  modules:\n    alpha: ''", CompositionDeclarationError),
    ("composition:\n  modules: []", CompositionDeclarationError),
    ("composition:\n  modules: {alpha: a.yaml}\nimports: {}", CompositionDeclarationError),
])
def test_strict_composition_yaml_and_exact_declaration_shape(
    tmp_path: Path, fragment: str, error: type[Exception],
) -> None:
    base = """dsl_version: 1
scenario: strict
clock: {start: '2026-01-01T00:00:00Z'}
initial_state: {}
steps: [{id: one, transition: null}]
"""
    _write(tmp_path / "root.yaml", base + fragment + "\n")
    with pytest.raises(error):
        load_composed_suite("root.yaml", composition_root=tmp_path)


@pytest.mark.parametrize("module", [
    "dsl_version: 1\nmodule: alpha\nresources: {a: 1, a: 2}\n",
    "dsl_version: 1\nmodule: alpha\nresources: {a: &x 1, b: *x}\n",
    "dsl_version: 1\nmodule: alpha\nresources: {a: !custom value}\n",
    "dsl_version: 1\nmodule: alpha\nresources: {1: value}\n",
    "dsl_version: 1\nmodule: alpha\nresources: {answer: 1.5}\n",
])
def test_strict_module_yaml_safety(tmp_path: Path, module: str) -> None:
    _write(tmp_path / "root.yaml", _root("    alpha: alpha.yaml"))
    _write(tmp_path / "alpha.yaml", module)
    with pytest.raises(ModuleParseError):
        load_composed_suite("root.yaml", composition_root=tmp_path)


def test_module_count_boundary_and_above_limit(tmp_path: Path) -> None:
    declarations = []
    for index in range(MAX_MODULES):
        alias = f"m{index}"
        declarations.append(f"    {alias}: {alias}.yaml")
        _write(tmp_path / f"{alias}.yaml", _module(alias, str(index)))
    _write(tmp_path / "root.yaml", _root("\n".join(declarations), resource="m0.answer"))
    accepted = load_composed_suite("root.yaml", composition_root=tmp_path)
    assert len(accepted.modules) == MAX_MODULES

    _write(tmp_path / "root.yaml", _root(
        "\n".join(declarations + ["    overflow: overflow.yaml"]),
        resource="m0.answer",
    ))
    with pytest.raises(CompositionBoundError, match=str(MAX_MODULES)):
        load_composed_suite("root.yaml", composition_root=tmp_path)


def test_oversized_module_rejected_before_read(tmp_path: Path) -> None:
    _write(tmp_path / "root.yaml", _root("    alpha: alpha.yaml"))
    with (tmp_path / "alpha.yaml").open("wb") as stream:
        stream.truncate(MAX_MODULE_DOCUMENT_BYTES + 1)
    with pytest.raises(CompositionBoundError, match=str(MAX_MODULE_DOCUMENT_BYTES)):
        load_composed_suite("root.yaml", composition_root=tmp_path)


def test_suite_manifest_identity_order_child_reference_and_v1_preservation(tmp_path: Path) -> None:
    suite = _suite(tmp_path)
    execution = execute_composed_suite(suite, "seed")
    manifest_bytes = canonical_suite_bytes(execution.suite_manifest)
    assert execution.suite_manifest.composition_contract_version == COMPOSITION_CONTRACT_VERSION
    assert execution.suite_manifest.composed_hash == suite.composed_hash
    assert tuple(execution.suite_manifest.module_hashes) == ("alpha",)
    assert len(execution.suite_manifest.child_runs) == 1
    assert execution.suite_manifest.child_runs[0].sha256 == hashlib.sha256(
        canonical_suite_bytes(execution.run_manifest)
    ).hexdigest()
    assert str(tmp_path).encode() not in manifest_bytes
    assert execution.result.manifest.domain_pack_versions == {}
    assert "composed_hash" not in execution.result.manifest.normalized()


def test_top_level_api_and_v1_parser_are_unchanged(tmp_path: Path) -> None:
    assert "load_composed_suite" not in scenario_engine.__all__
    assert VERSION == "1.0.0"
    root_without_composition = _root("    alpha: alpha.yaml").replace(
        "composition:\n  modules:\n    alpha: alpha.yaml\n", "",
    )
    from scenario_engine.dsl import DSLSchemaError, parse_yaml
    assert parse_yaml(root_without_composition).dsl_version == 1
    with pytest.raises(DSLSchemaError):
        parse_yaml(_root("    alpha: alpha.yaml"))
