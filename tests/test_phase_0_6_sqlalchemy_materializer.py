from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import tomllib
import unittest

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, MetaData, Numeric, String, Table, create_engine, event, select

from scenario_engine.dsl import compile_document, evaluate_scenario, parse_yaml, replay_scenario, run_scenario
from scenario_engine.ids import LogicalID
from scenario_engine.values import MISSING
from scenario_engine.adapters.sqlalchemy import (
    InvalidColumnBindingError, MaterializationExecutionError, MissingPrimaryKeyError,
    UnknownTableBindingError, UnsupportedMaterializedValueError, command_fingerprint,
    extract_row_commands, materialize_result, prepare_row_commands,
)


ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples" / "phase0_6_sqlalchemy_rows.yaml"


def scenario(rows, *, unrelated=False, faults=""):
    emissions = []
    if unrelated:
        emissions.append("      - {type: note, fields: {message: {$literal: ignored}}}")
    for table, values in rows:
        fields = ", ".join(f"{key}: {yaml_scalar(value)}" for key, value in values.items())
        emissions.append(
            "      - {type: sqlalchemy_row, fields: {table: {$literal: " + table
            + "}, values: {$literal: {" + fields + "}}}}"
        )
        if unrelated:
            emissions.append("      - {type: note, fields: {message: {$literal: ignored}}}")
    return f'''dsl_version: 1
scenario: materializer_test
clock: {{start: "2026-01-01T00:00:00Z"}}
initial_state: {{untouched: 0}}
{faults}steps:
  - id: emit_rows
    write: {{untouched: {{$literal: 0}}}}
    emit:
{chr(10).join(emissions)}
    transition: null
'''


def yaml_scalar(value):
    if value is None: return "null"
    if value is True: return "true"
    if value is False: return "false"
    if isinstance(value, int): return str(value)
    return str(value)


def run_text(text, seed="phase06"):
    return run_scenario(compile_document(parse_yaml(text)), seed)


def database(two=False, *, foreign_keys=False):
    engine = create_engine("sqlite:///:memory:")
    if foreign_keys:
        event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    metadata = MetaData()
    customers = Table("customers", metadata, Column("id", String, primary_key=True), Column("name", String))
    orders = Table("orders", metadata, Column("id", String, primary_key=True),
                   Column("customer_id", String, ForeignKey("customers.id")) if foreign_keys
                   else Column("customer_id", String),
                   Column("amount", Integer))
    metadata.create_all(engine)
    return engine, customers, orders


class Phase06SqlAlchemyMaterializerTests(unittest.TestCase):
    def test_sqlalchemy_extra_is_optional_and_core_dependency_contract_unchanged(self):
        doc = tomllib.loads((ROOT / "pyproject.toml").read_text())
        self.assertEqual(doc["project"]["dependencies"], ["PyYAML==6.0.3"])
        self.assertEqual(doc["project"]["optional-dependencies"]["pytest"], ["pytest>=9.1,<10"])
        self.assertEqual(doc["project"]["optional-dependencies"]["sqlalchemy"], ["SQLAlchemy>=2.0,<3"])

    def test_core_import_does_not_require_or_eagerly_import_sqlalchemy(self):
        code = "import sys; sys.modules['sqlalchemy']=None; import scenario_engine; assert 'scenario_engine.adapters.sqlalchemy' not in sys.modules"
        completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_extracts_only_sqlalchemy_row_artifacts_in_committed_artifact_order(self):
        commands = extract_row_commands(run_text(scenario([("customers", {"id": "a"}), ("orders", {"id": "b"})], unrelated=True)))
        self.assertEqual([(c.table_name, c.values["id"]) for c in commands], [("customers", "a"), ("orders", "b")])
        self.assertLess(commands[0].artifact_index, commands[1].artifact_index)

    def test_materializes_single_explicit_row_with_bound_table(self):
        engine, customers, _ = database(); report = materialize_result(engine, run_text(scenario([("customers", {"id": "a", "name": "Ada"})])), {"customers": customers})
        with engine.connect() as connection: self.assertEqual(connection.execute(select(customers)).mappings().all(), [{"id": "a", "name": "Ada"}])
        self.assertEqual(report.rows_inserted, 1)

    def test_materializes_multiple_rows_and_tables_in_artifact_order(self):
        engine, customers, orders = database(); result = run_text(scenario([("customers", {"id": "c", "name": "Ada"}), ("orders", {"id": "o", "customer_id": "c", "amount": 4})]))
        report = materialize_result(engine, result, {"customers": customers, "orders": orders})
        self.assertEqual(dict(report.per_table_counts), {"customers": 1, "orders": 1})

    def test_table_binding_mapping_order_is_irrelevant(self):
        result = run_text(scenario([("customers", {"id": "c"}), ("orders", {"id": "o"})])); reports = []
        for reverse in (False, True):
            engine, customers, orders = database(); pairs = [("customers", customers), ("orders", orders)]; reports.append(materialize_result(engine, result, dict(reversed(pairs)) if reverse else dict(pairs)))
        self.assertEqual(reports[0], reports[1])

    def test_unknown_table_binding_is_rejected_before_database_write(self):
        engine, customers, _ = database(); result = run_text(scenario([("customers", {"id": "a"}), ("absent", {"id": "b"})]))
        with self.assertRaises(UnknownTableBindingError): materialize_result(engine, result, {"customers": customers})
        with engine.connect() as connection: self.assertEqual(connection.execute(select(customers)).all(), [])

    def test_unknown_column_is_rejected_before_database_write(self):
        engine, customers, _ = database(); result = run_text(scenario([("customers", {"id": "a", "unknown": "x"})]))
        with self.assertRaises(InvalidColumnBindingError): materialize_result(engine, result, {"customers": customers})
        with engine.connect() as connection: self.assertEqual(connection.execute(select(customers)).all(), [])

    def test_missing_primary_key_value_is_rejected_before_database_write(self):
        engine = create_engine("sqlite:///:memory:"); metadata = MetaData(); table = Table("pairs", metadata, Column("a", String, primary_key=True), Column("b", String, primary_key=True)); metadata.create_all(engine)
        with self.assertRaises(MissingPrimaryKeyError): materialize_result(engine, run_text(scenario([("pairs", {"a": "x"})])), {"pairs": table})

    def test_missing_semantic_value_is_rejected_before_database_write(self):
        engine, customers, _ = database(); command = extract_row_commands(run_text(scenario([("customers", {"id": "a"})])))[0]
        altered = type(command)(command.artifact_index, command.table_name, {"id": MISSING})
        with self.assertRaises(UnsupportedMaterializedValueError): prepare_row_commands((altered,), {"customers": customers})

    def test_nested_list_and_map_values_are_rejected_in_narrow_scalar_contract(self):
        engine, customers, _ = database(); base = extract_row_commands(run_text(scenario([("customers", {"id": "a"})])))[0]
        for value in ([1], {"a": 1}):
            with self.assertRaises(UnsupportedMaterializedValueError): prepare_row_commands((type(base)(0, "customers", {"id": value}),), {"customers": customers})

    def test_supported_semantic_scalars_prepare_without_float_or_repr_coercion(self):
        engine = create_engine("sqlite:///:memory:"); metadata = MetaData(); table = Table("scalars", metadata, Column("id", Integer, primary_key=True), Column("d", Numeric), Column("b", Boolean), Column("s", String), Column("n", String), Column("dt", DateTime(timezone=True)), Column("du", String))
        base = extract_row_commands(run_text(scenario([("customers", {"id": "a"})])))[0]; now = datetime(2026, 1, 1, tzinfo=timezone.utc); delta = timedelta(seconds=2); values = {"id": 1, "d": Decimal("1.20"), "b": True, "s": "x", "n": None, "dt": now, "du": delta}
        prepared = prepare_row_commands((type(base)(0, "scalars", values),), {"scalars": table})[0][2]
        self.assertIsInstance(prepared["d"], Decimal); self.assertIs(prepared["b"], True); self.assertIs(prepared["dt"], now); self.assertIs(prepared["du"], delta)

    def test_logical_id_materializes_as_stable_string_value(self):
        engine, customers, _ = database(); logical = LogicalID("12345678-1234-5678-9234-567812345678"); base = extract_row_commands(run_text(scenario([("customers", {"id": "a"})])))[0]
        prepared = prepare_row_commands((type(base)(0, "customers", {"id": logical}),), {"customers": customers})[0][2]
        self.assertEqual(prepared["id"], logical.value); self.assertNotEqual(prepared["id"], repr(logical))

    def test_all_commands_are_prevalidated_before_transaction_begins(self):
        self.test_unknown_table_binding_is_rejected_before_database_write()

    def test_database_integrity_failure_rolls_back_entire_materialization(self):
        engine, customers, _ = database(); result = run_text(scenario([("customers", {"id": "same", "name": "A"}), ("customers", {"id": "same", "name": "B"})]))
        with self.assertRaisesRegex(MaterializationExecutionError, r"command 1 table customers: IntegrityError"): materialize_result(engine, result, {"customers": customers})
        with engine.connect() as connection: self.assertEqual(connection.execute(select(customers)).all(), [])

    def test_zero_sqlalchemy_row_artifacts_is_deterministic_noop(self):
        engine, customers, _ = database(); result = run_text(scenario([], unrelated=True)); a = materialize_result(engine, result, {}); b = materialize_result(engine, result, {})
        self.assertEqual(a, b); self.assertEqual((a.commands_attempted, a.rows_inserted, dict(a.per_table_counts)), (0, 0, {}))

    def test_materialization_report_is_deterministic_and_contains_no_database_generated_identity(self):
        reports = []
        for _ in range(2):
            engine, customers, _ = database(); reports.append(materialize_result(engine, run_text(scenario([("customers", {"id": "a"})])), {"customers": customers}))
        self.assertEqual(reports[0], reports[1]); self.assertEqual(set(reports[0].__dataclass_fields__), {"commands_attempted", "rows_inserted", "per_table_counts", "command_fingerprint"})

    def test_same_scenario_and_replay_produce_identical_materialization_commands(self):
        text = EXAMPLE.read_text(); original = run_text(text); replay = replay_scenario(text, original.manifest)
        self.assertEqual(original.to_json_bytes(), replay.to_json_bytes()); self.assertEqual(extract_row_commands(original), extract_row_commands(replay)); self.assertEqual(command_fingerprint(extract_row_commands(original)), command_fingerprint(extract_row_commands(replay)))

    def test_successful_faulted_replay_produces_identical_materialization_commands(self):
        faults = "faults:\n  - {id: harmless, enabled: true, at: before_step, selector: {step: emit_rows}, operator: {override_write: {path: untouched, value: {$literal: 1}}}}\n"
        text = scenario([("customers", {"id": "a"})], faults=faults); original = run_text(text); replay = replay_scenario(text, original.manifest)
        self.assertEqual(extract_row_commands(original), extract_row_commands(replay))

    def test_materializer_does_not_change_scenario_result_manifest_or_stable_bytes(self):
        result = run_text(EXAMPLE.read_text()); before = (result.normalized(), result.to_json_bytes(), result.manifest, result.trace(), result.provenance)
        engine, customers, orders = database(); materialize_result(engine, result, {"customers": customers, "orders": orders})
        self.assertEqual(before, (result.normalized(), result.to_json_bytes(), result.manifest, result.trace(), result.provenance))

    def test_adapter_does_not_create_schema_reflect_tables_or_execute_raw_sql(self):
        source = (ROOT / "src/scenario_engine/adapters/sqlalchemy.py").read_text(); tree = ast.parse(source)
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]; attrs = {n.func.attr for n in calls if isinstance(n.func, ast.Attribute)}; names = {n.func.id for n in calls if isinstance(n.func, ast.Name)}
        self.assertTrue({"begin", "execute", "insert"} <= attrs); self.assertFalse(attrs & {"create_all", "reflect", "update", "delete"}); self.assertFalse(names & {"create_engine", "text", "Session"})

    def test_foreign_key_order_can_be_satisfied_by_explicit_artifact_order(self):
        engine, customers, orders = database(foreign_keys=True); result = run_text(scenario([("customers", {"id": "c"}), ("orders", {"id": "o", "customer_id": "c", "amount": 1})])); materialize_result(engine, result, {"customers": customers, "orders": orders})
        with engine.connect() as connection: self.assertEqual(connection.execute(select(orders.c.customer_id)).scalar_one(), "c")

    def test_real_pytest_harness_result_composes_with_sqlalchemy_materializer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test_real.py"; path.write_text(textwrap.dedent(f'''\
                from pathlib import Path
                from sqlalchemy import *
                from scenario_engine.adapters.sqlalchemy import *
                pytest_plugins=["scenario_engine.pytest_plugin"]
                def test_real(scenario_engine):
                    text=Path({str(EXAMPLE)!r}).read_text(); result=scenario_engine.run_text(text,root_seed="p")
                    engine=create_engine("sqlite:///:memory:"); metadata=MetaData(); customers=Table("customers",metadata,Column("id",String,primary_key=True),Column("name",String)); orders=Table("orders",metadata,Column("id",String,primary_key=True),Column("customer_id",String),Column("amount",Integer)); metadata.create_all(engine)
                    report=materialize_result(engine,result,{{"customers":customers,"orders":orders}}); replay=scenario_engine.replay_text(text,result.manifest); assert report.rows_inserted==2; assert command_fingerprint(extract_row_commands(result))==command_fingerprint(extract_row_commands(replay))
            '''))
            completed = subprocess.run([sys.executable, "-m", "pytest", "-q", str(path)], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_phase0_6_example_and_all_prior_examples_remain_compatible(self):
        cases = [("phase0_1b_cart.yaml", {}), ("phase0_3_resources.yaml", {"customer_id": "c", "maximum_quantity": 5}), ("phase0_4_control_flow.yaml", {"premium": True, "retry_count": 1, "customer_id": "c"})]
        for name, inputs in cases:
            text = (ROOT / "examples" / name).read_text(); result = run_scenario(compile_document(parse_yaml(text)), "p", inputs=inputs); self.assertEqual(result.to_json_bytes(), replay_scenario(text, result.manifest, inputs=inputs).to_json_bytes())
        evaluation = evaluate_scenario(compile_document(parse_yaml((ROOT / "examples/phase0_5_oracle_fault.yaml").read_text())), "p"); self.assertTrue(evaluation.report.passed)
        engine, customers, orders = database(); self.assertEqual(materialize_result(engine, run_text(EXAMPLE.read_text()), {"customers": customers, "orders": orders}).rows_inserted, 2)
