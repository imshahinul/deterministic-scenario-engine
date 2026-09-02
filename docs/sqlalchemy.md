# SQLAlchemy Core adapter

SQLAlchemy support is an optional post-result adapter. Install it from the local
source checkout with:

```console
python3 -m venv /tmp/scenario-engine-sqlalchemy
/tmp/scenario-engine-sqlalchemy/bin/python -m pip install '.[sqlalchemy]'
```

## Contract

The adapter supports SQLAlchemy Core only. A scenario emits ordered
`sqlalchemy_row` artifacts whose value has `table` and `values`. The caller
supplies explicit table-name-to-`Table` bindings. The adapter:

1. extracts row commands in artifact order;
2. validates every table binding, column/value, supported semantic value, and
   required primary-key value before any write;
3. prepares deterministic commands and a canonical command fingerprint; and
4. executes all inserts in one `engine.begin()` transaction.

Artifact order is insertion order, so callers can deliberately satisfy foreign
keys. Preparation failure performs no writes. Execution failure rolls back the
transaction. `MaterializationReport` records attempted commands, inserted rows,
per-table counts, and the command fingerprint.

`ScenarioState` remains independent of the database. The adapter does not
provide ORM state, schema creation/management, reflection-driven model discovery,
a raw-SQL DSL, or database-generated identity as deterministic ground truth.

## Local SQLite example

This uses [`examples/sqlalchemy_rows.yaml`](../examples/sqlalchemy_rows.yaml) and
an in-memory SQLite database. Explicit schema construction is caller-owned:

```python
from pathlib import Path

from sqlalchemy import Column, ForeignKey, Integer, MetaData, String, Table, create_engine, select

from scenario_engine import compile_document, parse_yaml, run_scenario
from scenario_engine.adapters.sqlalchemy import materialize_result

text = Path("examples/sqlalchemy_rows.yaml").read_text(encoding="utf-8")
result = run_scenario(compile_document(parse_yaml(text)), "sqlalchemy-guide")

metadata = MetaData()
customers = Table(
    "customers",
    metadata,
    Column("id", String, primary_key=True),
    Column("name", String, nullable=False),
)
orders = Table(
    "orders",
    metadata,
    Column("id", String, primary_key=True),
    Column("customer_id", String, ForeignKey("customers.id"), nullable=False),
    Column("amount", Integer, nullable=False),
)
engine = create_engine("sqlite+pysqlite:///:memory:")
try:
    metadata.create_all(engine)
    report = materialize_result(
        engine,
        result,
        {"customers": customers, "orders": orders},
    )
    assert report.rows_inserted == 2
    with engine.connect() as connection:
        assert connection.execute(select(customers.c.name)).scalar_one() == "Ada"
finally:
    engine.dispose()
```

Materialization does not alter the `ScenarioResult` or its reproducibility
manifest. Database effects are downstream caller-managed effects.
