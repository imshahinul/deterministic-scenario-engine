"""Narrow, insert-only SQLAlchemy Core materialization adapter."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Mapping

try:
    from sqlalchemy import Table
    from sqlalchemy.engine import Engine
except ImportError as exc:  # pragma: no cover - exercised in an isolated process
    raise ImportError(
        "scenario_engine.adapters.sqlalchemy requires the optional "
        "'SQLAlchemy>=2.0,<3' dependency"
    ) from exc

from scenario_engine.ids import LogicalID
from scenario_engine.result import ScenarioResult
from scenario_engine.values import MISSING, fingerprint


class SqlAlchemyMaterializerError(ValueError):
    """Base class for deterministic adapter errors."""


class InvalidRowArtifactError(SqlAlchemyMaterializerError):
    pass


class UnknownTableBindingError(SqlAlchemyMaterializerError):
    pass


class InvalidTableBindingError(SqlAlchemyMaterializerError):
    pass


class InvalidColumnBindingError(SqlAlchemyMaterializerError):
    pass


class MissingPrimaryKeyError(SqlAlchemyMaterializerError):
    pass


class UnsupportedMaterializedValueError(SqlAlchemyMaterializerError):
    pass


class MaterializationExecutionError(SqlAlchemyMaterializerError):
    pass


@dataclass(frozen=True, slots=True)
class SqlAlchemyRowCommand:
    artifact_index: int
    table_name: str
    values: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class MaterializationReport:
    commands_attempted: int
    rows_inserted: int
    per_table_counts: Mapping[str, int]
    command_fingerprint: str


def _freeze_values(values: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(values))


def extract_row_commands(result: ScenarioResult) -> tuple[SqlAlchemyRowCommand, ...]:
    """Extract validated-shape row commands in committed artifact order."""
    if not isinstance(result, ScenarioResult):
        raise TypeError("result must be a ScenarioResult")
    commands = []
    for artifact_index, artifact in enumerate(result.artifacts):
        if artifact.artifact_type != "sqlalchemy_row":
            continue
        payload = artifact.value
        if not isinstance(payload, Mapping) or set(payload) != {"table", "values"}:
            raise InvalidRowArtifactError(
                f"sqlalchemy_row artifact {artifact_index} payload must contain exactly table and values"
            )
        table_name, values = payload["table"], payload["values"]
        if not isinstance(table_name, str) or not table_name:
            raise InvalidRowArtifactError(
                f"sqlalchemy_row artifact {artifact_index} table must be a non-empty string"
            )
        if not isinstance(values, Mapping) or not values or not all(
            isinstance(name, str) and name for name in values
        ):
            raise InvalidRowArtifactError(
                f"sqlalchemy_row artifact {artifact_index} values must be a non-empty string-keyed mapping"
            )
        commands.append(SqlAlchemyRowCommand(artifact_index, table_name, _freeze_values(values)))
    return tuple(commands)


def _prepare_value(value: Any, command_index: int, column_name: str) -> Any:
    if value is MISSING:
        raise UnsupportedMaterializedValueError(
            f"command {command_index} column {column_name}: MISSING is not SQL NULL"
        )
    if isinstance(value, LogicalID):
        return value.value
    if value is None or isinstance(value, (bool, int, Decimal, str, timedelta)):
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise UnsupportedMaterializedValueError(
                f"command {command_index} column {column_name}: datetime must be timezone-aware"
            )
        return value
    raise UnsupportedMaterializedValueError(
        f"command {command_index} column {column_name}: unsupported {type(value).__name__} value"
    )


def prepare_row_commands(
    commands: tuple[SqlAlchemyRowCommand, ...], tables: Mapping[str, Table]
) -> tuple[tuple[SqlAlchemyRowCommand, Table, Mapping[str, Any]], ...]:
    """Purely prevalidate and prepare every command before transaction entry."""
    prepared = []
    for command_index, command in enumerate(commands):
        if command.table_name not in tables:
            raise UnknownTableBindingError(
                f"command {command_index}: unknown table binding {command.table_name}"
            )
        table = tables[command.table_name]
        if not isinstance(table, Table):
            raise InvalidTableBindingError(
                f"command {command_index}: binding {command.table_name} is not a SQLAlchemy Table"
            )
        unknown = sorted(set(command.values) - set(table.c.keys()))
        if unknown:
            raise InvalidColumnBindingError(
                f"command {command_index} table {command.table_name}: unknown columns {','.join(unknown)}"
            )
        primary_keys = tuple(column.name for column in table.primary_key.columns)
        if not primary_keys:
            raise MissingPrimaryKeyError(
                f"command {command_index} table {command.table_name}: target table has no primary key"
            )
        missing = tuple(name for name in primary_keys if name not in command.values)
        if missing:
            raise MissingPrimaryKeyError(
                f"command {command_index} table {command.table_name}: missing primary key columns {','.join(missing)}"
            )
        values = {name: _prepare_value(command.values[name], command_index, name)
                  for name in sorted(command.values)}
        prepared.append((command, table, MappingProxyType(values)))
    return tuple(prepared)


def command_fingerprint(commands: tuple[SqlAlchemyRowCommand, ...]) -> str:
    intent = [{
        "artifact_index": command.artifact_index,
        "table": command.table_name,
        "values": dict(command.values),
    } for command in commands]
    return fingerprint(intent)


def materialize_result(
    engine: Engine, result: ScenarioResult, tables: Mapping[str, Table]
) -> MaterializationReport:
    """Prevalidate all commands, then insert all rows in one transaction."""
    if not isinstance(engine, Engine):
        raise TypeError("engine must be a SQLAlchemy Engine")
    commands = extract_row_commands(result)
    digest = command_fingerprint(commands)
    if not commands:
        return MaterializationReport(0, 0, MappingProxyType({}), digest)
    prepared = prepare_row_commands(commands, tables)
    try:
        with engine.begin() as connection:
            for command_index, (command, table, values) in enumerate(prepared):
                try:
                    connection.execute(table.insert().values(**dict(values)))
                except Exception as exc:
                    raise MaterializationExecutionError(
                        f"command {command_index} table {command.table_name}: {type(exc).__name__}"
                    ) from exc
    except MaterializationExecutionError:
        raise
    counts = Counter(command.table_name for command in commands)
    return MaterializationReport(
        len(commands), len(commands),
        MappingProxyType({name: counts[name] for name in sorted(counts)}), digest,
    )


__all__ = [
    "InvalidColumnBindingError", "InvalidRowArtifactError", "InvalidTableBindingError",
    "MaterializationExecutionError", "MaterializationReport", "MissingPrimaryKeyError",
    "SqlAlchemyMaterializerError", "SqlAlchemyRowCommand", "UnknownTableBindingError",
    "UnsupportedMaterializedValueError", "command_fingerprint", "extract_row_commands",
    "materialize_result", "prepare_row_commands",
]
