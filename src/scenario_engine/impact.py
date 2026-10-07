"""Conservative static may-impact analysis for validated DSL 1 definitions."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
import json
from typing import Any, Iterable, Mapping

from scenario_engine.definition_diff import (
    DEFINITION_DIFF_CONTRACT, DefinitionChange, DefinitionChangeKind,
    DefinitionDiff, compare_definitions,
)
from scenario_engine.diagnostics import semantic_address
from scenario_engine.dsl import compile_document
from scenario_engine.dsl.models import ScenarioDocument, StepDocument


IMPACT_CONTRACT = "scenario.impact/1"
DEPENDENCY_GRAPH_VERSION = "scenario.dependency-graph.dsl1/1"
MAX_IMPACT_NODES = 100_000
MAX_IMPACT_EDGES = 500_000
MAX_IMPACT_DEPTH = 256
MAX_IMPACT_RECORDS = 100_000


class ImpactClassification(str, Enum):
    DIRECT = "DIRECT"
    TRANSITIVE_POSSIBLE = "TRANSITIVE_POSSIBLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ImpactRecord:
    source_change: DefinitionChange
    affected_semantic_path: str
    classification: ImpactClassification
    dependency_kind: str

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "affected_semantic_path": self.affected_semantic_path,
            "classification": self.classification.value,
            "dependency_kind": self.dependency_kind,
            "source_change": {
                "change_kind": self.source_change.change_kind.value,
                "semantic_path": self.source_change.semantic_path,
            },
        }


@dataclass(frozen=True, slots=True)
class ImpactAnalysis:
    definition_diff: DefinitionDiff
    records: tuple[ImpactRecord, ...]
    eligible_entity_count: int
    schema: str = IMPACT_CONTRACT

    def to_jsonable(self) -> dict[str, Any]:
        affected = {record.affected_semantic_path for record in self.records}
        numerator = len(affected)
        denominator = self.eligible_entity_count
        reduced = Fraction(numerator, denominator) if denominator else Fraction(0, 1)
        counts = {classification.value: 0 for classification in ImpactClassification}
        strongest: dict[str, ImpactClassification] = {}
        rank = {ImpactClassification.TRANSITIVE_POSSIBLE: 1, ImpactClassification.UNKNOWN: 2,
                ImpactClassification.DIRECT: 3}
        for record in self.records:
            previous = strongest.get(record.affected_semantic_path)
            if previous is None or rank[record.classification] > rank[previous]:
                strongest[record.affected_semantic_path] = record.classification
        for classification in strongest.values():
            counts[classification.value] += 1
        return {
            "amplification": {
                "denominator": denominator,
                "denominator_definition": "distinct semantic-addressed entities in the bounded union of the validated before and target dependency graphs",
                "numerator": numerator,
                "numerator_definition": "distinct entities classified DIRECT, TRANSITIVE_POSSIBLE, or UNKNOWN for the structural change set",
                "reduced_fraction": f"{reduced.numerator}/{reduced.denominator}",
            },
            "claims": {"behavioral_equivalence": False, "complete_impact_proof": False,
                       "unknown_means_unaffected": False},
            "definition_diff": {
                "change_count": len(self.definition_diff.changes),
                "contract": DEFINITION_DIFF_CONTRACT,
                "left_hash": self.definition_diff.left_hash,
                "right_hash": self.definition_diff.right_hash,
            },
            "dependency_graph": {"identity": DEPENDENCY_GRAPH_VERSION,
                                 "uses_semantic_addresses": True},
            "dsl_version": self.definition_diff.dsl_version,
            "impacts": [record.to_jsonable() for record in self.records],
            "schema": self.schema,
            "side_selection": "ADDED uses target; REMOVED uses before; CHANGED uses the union of both validated definitions",
            "summary": {"counts": counts, "impacted_entity_count": numerator},
        }

    def to_json_bytes(self) -> bytes:
        return json.dumps(self.to_jsonable(), ensure_ascii=False, allow_nan=False,
                          sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass(frozen=True, slots=True)
class _Edge:
    target: str
    kind: str
    unknown: bool = False


class _Graph:
    def __init__(self) -> None:
        self.nodes: set[str] = set()
        self.edges: dict[str, set[_Edge]] = {}
        self.edge_count = 0

    def node(self, path: str) -> str:
        self.nodes.add(path)
        if len(self.nodes) > MAX_IMPACT_NODES:
            raise ValueError(f"impact dependency graph exceeds {MAX_IMPACT_NODES} nodes")
        return path

    def edge(self, source: str, target: str, kind: str, *, unknown: bool = False) -> None:
        self.node(source); self.node(target)
        edges = self.edges.setdefault(source, set())
        prior = len(edges); edges.add(_Edge(target, kind, unknown))
        self.edge_count += len(edges) - prior
        if self.edge_count > MAX_IMPACT_EDGES:
            raise ValueError(f"impact dependency graph exceeds {MAX_IMPACT_EDGES} edges")

    def merge(self, other: _Graph) -> None:
        for node in other.nodes:
            self.node(node)
        for source, edges in other.edges.items():
            for edge in edges:
                self.edge(source, edge.target, edge.kind, unknown=edge.unknown)


def _address(*components: tuple[str, str]) -> str:
    result = semantic_address(*components)
    if result is None:
        raise ValueError("impact entity cannot be represented by scenario.semantic-address/1")
    return result


def _refs(node: Any) -> Iterable[tuple[str, str]]:
    if isinstance(node, Mapping):
        for key, value in node.items():
            if key in {"$state", "$local", "$derived", "$resource", "$scope"}:
                yield key[1:], str(value)
            else:
                yield from _refs(value)
    elif isinstance(node, (list, tuple)):
        for value in node:
            yield from _refs(value)


def _reference_path(kind: str, name: str, base: tuple[tuple[str, str], ...]) -> str:
    if kind == "state":
        return _address(("state", name))
    if kind == "resource":
        return _address(("resource", name.split(".", 1)[0]))
    if kind == "local":
        return _address(*base, ("generator", name))
    if kind == "derived":
        return _address(*base, ("derive", name))
    return _address(*base, ("x-scope", name))


def _expression_edges(graph: _Graph, node: Any, target: str,
                      base: tuple[tuple[str, str], ...], kind: str,
                      *, opaque: bool = False) -> None:
    for reference_kind, name in _refs(node):
        graph.edge(_reference_path(reference_kind, name, base), target, kind,
                   unknown=opaque or reference_kind == "scope")


def _control_targets(step: StepDocument) -> tuple[str, ...]:
    if step.call is not None:
        return (str(step.call["subflow"]),)
    if step.repeat is not None:
        return (str(step.repeat["subflow"]),)
    if step.branch is not None:
        result = [str(case["subflow"]) for case in step.branch["cases"]]
        if "else" in step.branch:
            result.append(str(step.branch["else"]["subflow"]))
        return tuple(result)
    return ()


def _add_step(graph: _Graph, step: StepDocument,
              prefix: tuple[tuple[str, str], ...] = ()) -> None:
    base = (*prefix, ("step", step.step_id))
    step_path = graph.node(_address(*base))
    for name, expression in step.generate.items():
        path = _address(*base, ("generator", name)); graph.edge(step_path, path, "STEP_COMPONENT")
        _expression_edges(graph, expression, path, base, "GENERATOR_ARGUMENT", opaque="$plugin" in expression)
    for name, expression in step.derive.items():
        path = _address(*base, ("derive", name)); graph.edge(step_path, path, "STEP_COMPONENT")
        _expression_edges(graph, expression, path, base, "EXPRESSION_REFERENCE")
    for name, expression in step.write.items():
        path = _address(*base, ("write", name)); graph.edge(step_path, path, "STEP_COMPONENT")
        _expression_edges(graph, expression, path, base, "EXPRESSION_REFERENCE")
        graph.edge(path, _address(("state", name)), "STATE_WRITE")
    if step.emit:
        path = _address(*base, ("emit", "emissions")); graph.edge(step_path, path, "STEP_COMPONENT")
        _expression_edges(graph, step.emit, path, base, "EMISSION_FIELD_REFERENCE")
    graph.edge(step_path, _address(*base, ("x-advance", "duration")), "STEP_COMPONENT")
    transition = _address(*base, ("transition", "target")); graph.edge(step_path, transition, "STEP_COMPONENT")
    if step.transition is not None:
        graph.edge(transition, _address(*prefix, ("step", step.transition)), "TRANSITION_TARGET")
    if step.control_kind is not None:
        control = _address(*base, ("x-control", step.control_kind)); graph.edge(step_path, control, "STEP_COMPONENT")
        body = getattr(step, step.control_kind)
        _expression_edges(graph, body, control, base, "CONTROL_EXPRESSION")
        for target in _control_targets(step):
            graph.edge(control, _address(("x-subflow", target)), "CONTROL_SUBFLOW")


def _graph(document: ScenarioDocument) -> _Graph:
    graph = _Graph()
    graph.node(_address(("x-definition", "scenario")))
    graph.node(_address(("x-definition", "clock")))
    initial = graph.node(_address(("x-definition", "initial-state")))
    for name in document.initial_state:
        graph.edge(initial, _address(("state", name)), "INITIAL_STATE_FIELD")
    for name, value in document.resources.items():
        path = graph.node(_address(("resource", name)))
        for reference_kind, reference in _refs(value):
            if reference_kind == "resource":
                graph.edge(_address(("resource", reference.split(".", 1)[0])), path, "RESOURCE_REFERENCE")
        if isinstance(value, Mapping) and "$ref" in value:
            graph.edge(_address(("resource", str(value["$ref"]).split(".", 1)[0])), path,
                       "RESOURCE_REFERENCE")
    for item in document.validators:
        path = graph.node(_address(("x-validator", str(item["id"]))))
        graph.edge(_address(("resource", str(item["resource"]))), path, "VALIDATOR_RESOURCE")
    for item in document.constraints:
        path = graph.node(_address(("constraint", str(item["id"]))))
        _expression_edges(graph, item["check"], path, (), "CONSTRAINT_REFERENCE")
    for item in document.invariants:
        path = graph.node(_address(("invariant", str(item["id"]))))
        _expression_edges(graph, item["check"], path, (), "INVARIANT_REFERENCE")
    oracle = graph.node(_address(("oracle", "expectation"))) if document.oracle is not None else None
    if document.oracle is not None:
        for kind in ("constraints", "invariants"):
            for name in document.oracle["expected"][kind]:
                graph.edge(_address((kind[:-1], str(name))), oracle, "ORACLE_EXPECTATION")
    for step in document.steps:
        _add_step(graph, step)
    for subflow, steps in document.subflows.items():
        root = graph.node(_address(("x-subflow", subflow)))
        for step in steps:
            path = _address(("x-subflow", subflow), ("step", step.step_id))
            graph.edge(root, path, "SUBFLOW_MEMBER"); _add_step(graph, step, (("x-subflow", subflow),))
    for item in document.faults:
        fault = graph.node(_address(("fault", str(item["id"]))))
        operation, body = next(iter(item["operator"].items()))
        if item["at"] == "before_validation":
            target = _address(("resource", str(body["path"])))
            _expression_edges(graph, body["value"], fault, (), "FAULT_VALUE_REFERENCE")
        else:
            step_id = str(item["selector"]["step"])
            prefix = tuple(("x-subflow", name) for name in item["selector"].get("subflow_path", ()))
            base = (*prefix, ("step", step_id))
            target = (_address(*base, ("write", str(body["path"]))) if operation == "override_write" else
                      _address(*base, ("generator", str(body["name"]))) if operation == "override_local" else
                      _address(*base, ("emit", "emissions")))
            if operation != "suppress_emissions":
                _expression_edges(graph, body["value"], fault, base, "FAULT_VALUE_REFERENCE")
        graph.edge(fault, target, "FAULT_TARGET"); graph.edge(target, fault, "FAULT_TARGETED_BY")
        if oracle is not None:
            graph.edge(fault, oracle, "ORACLE_FAULT_EXPECTATION")
    return graph


def _paths_for_change(change: DefinitionChange, before: _Graph, target: _Graph) -> tuple[str, ...]:
    selected = target if change.change_kind is DefinitionChangeKind.ADDED else before if change.change_kind is DefinitionChangeKind.REMOVED else None
    nodes = selected.nodes if selected is not None else before.nodes | target.nodes
    descendants = tuple(node for node in nodes if node == change.semantic_path or node.startswith(change.semantic_path + "/"))
    return descendants or (change.semantic_path,)


def analyze_impact(left: ScenarioDocument, right: ScenarioDocument,
                   definition_diff: DefinitionDiff | None = None) -> ImpactAnalysis:
    """Analyze conservative static impact using the authoritative structural diff."""
    if not isinstance(left, ScenarioDocument) or not isinstance(right, ScenarioDocument):
        raise TypeError("impact inputs must be ScenarioDocument values")
    compile_document(left); compile_document(right)
    authoritative = compare_definitions(left, right)
    if definition_diff is not None and definition_diff != authoritative:
        raise ValueError("impact definition diff does not match validated definitions")
    difference = authoritative if definition_diff is None else definition_diff
    before, target = _graph(left), _graph(right)
    union = _Graph(); union.merge(before); union.merge(target)
    records: list[ImpactRecord] = []
    for change in difference.changes:
        direct = set(_paths_for_change(change, before, target))
        best: dict[str, tuple[ImpactClassification, str]] = {
            path: (ImpactClassification.DIRECT, "STRUCTURAL_CHANGE") for path in direct}
        queue = deque((path, False, 0) for path in sorted(direct))
        visited: set[tuple[str, bool]] = {(path, False) for path in direct}
        while queue:
            source, uncertain, depth = queue.popleft()
            if depth >= MAX_IMPACT_DEPTH:
                best[source] = (ImpactClassification.UNKNOWN, "MAX_GRAPH_DEPTH"); continue
            for edge in sorted(union.edges.get(source, ()), key=lambda item: (item.target.encode(), item.kind, item.unknown)):
                next_uncertain = uncertain or edge.unknown
                state = (edge.target, next_uncertain)
                if state not in visited:
                    visited.add(state); queue.append((edge.target, next_uncertain, depth + 1))
                if edge.target in direct:
                    continue
                classification = ImpactClassification.UNKNOWN if next_uncertain else ImpactClassification.TRANSITIVE_POSSIBLE
                previous = best.get(edge.target)
                if previous is None or (classification is ImpactClassification.UNKNOWN and previous[0] is ImpactClassification.TRANSITIVE_POSSIBLE):
                    best[edge.target] = (classification, "OPAQUE_OR_UNRESOLVED_DEPENDENCY" if next_uncertain else edge.kind)
        for path, (classification, reason) in best.items():
            records.append(ImpactRecord(change, path, classification, reason))
            if len(records) > MAX_IMPACT_RECORDS:
                raise ValueError(f"impact report exceeds {MAX_IMPACT_RECORDS} records")
    records.sort(key=lambda item: (item.source_change.semantic_path.encode("utf-8"),
                                   item.source_change.change_kind.value,
                                   item.affected_semantic_path.encode("utf-8"),
                                   item.classification.value, item.dependency_kind))
    return ImpactAnalysis(difference, tuple(records), len(union.nodes))


def render_impact_analysis(analysis: ImpactAnalysis) -> str:
    value = analysis.to_jsonable(); amplification = value["amplification"]
    lines = [f"scenario conservative impact analysis: {value['summary']['impacted_entity_count']} impacted entity(s)",
             f"change amplification: {amplification['numerator']}/{amplification['denominator']} (reduced {amplification['reduced_fraction']})"]
    for record in analysis.records:
        lines.append(f"{record.classification.value} {record.affected_semantic_path} <- "
                     f"{record.source_change.change_kind.value} {record.source_change.semantic_path} [{record.dependency_kind}]")
    lines.append("no behavioral equivalence or complete impact proof is claimed; UNKNOWN does not mean unaffected")
    return "\n".join(lines)


__all__ = ["DEPENDENCY_GRAPH_VERSION", "IMPACT_CONTRACT", "ImpactAnalysis",
           "ImpactClassification", "ImpactRecord", "analyze_impact", "render_impact_analysis"]
