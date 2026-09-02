# Schemathesis integration

Install the optional integration from a local source checkout:

```console
python3 -m venv /tmp/scenario-engine-schemathesis
/tmp/scenario-engine-schemathesis/bin/python -m pip install '.[schemathesis]'
```

Schemathesis generates API case objects from an API schema. Scenario Engine
executes a local deterministic business history. The adapter binds selected
normalized `ScenarioResult` paths into generated case locations. Composition is
local: the adapter does not send HTTP requests, does not call the case, and does
not execute an API operation. Any network execution is the responsibility of
the caller or its test framework.

[`examples/openapi.yaml`](../examples/openapi.yaml) is OpenAPI support input—not
Scenario Engine DSL. [`examples/api_scenario.yaml`](../examples/api_scenario.yaml)
is the corresponding DSL 1 scenario.

Supported submodule surface:

- `SchemathesisCaseBindings`
- `BoundSchemathesisCase`
- `bind_case()`
- `operation_cases()`
- `SchemathesisIntegrationError`, `ScenarioBindingError`, and
  `UnsupportedHTTPBindingValueError`

## Local OpenAPI composition

```python
from copy import deepcopy
from pathlib import Path

import schemathesis
import yaml
from hypothesis import find, settings, strategies as st

from scenario_engine.integrations.hypothesis import scenario_cases
from scenario_engine.integrations.schemathesis import SchemathesisCaseBindings, bind_case
from scenario_engine.reference_packs.ecommerce import ecommerce_registry

scenario_text = Path("examples/api_scenario.yaml").read_text(encoding="utf-8")
openapi = yaml.safe_load(Path("examples/openapi.yaml").read_text(encoding="utf-8"))
operation = schemathesis.openapi.from_dict(deepcopy(openapi))["/orders"]["POST"]
draw_settings = settings(max_examples=20, database=None, deadline=None)

scenario = find(
    scenario_cases(
        scenario_text,
        root_seed="schemathesis-guide",
        run_indexes=st.just(0),
        inputs=st.just({
            "customer_id": "customer-api",
            "email_domain": "example.test",
            "quantity": 2,
        }),
        plugins=ecommerce_registry(),
    ),
    lambda item: True,
    settings=draw_settings,
)
case = find(operation.as_strategy(), lambda item: True, settings=draw_settings)

bindings = SchemathesisCaseBindings(
    headers={"X-Customer-ID": "state.customer_id"},
    body={
        "order_number": "state.order_number",
        "customer_email": "state.customer_email",
        "quantity": "state.quantity",
    },
)
returned = bind_case(case, scenario.result, bindings)
assert returned is case
assert case.headers["X-Customer-ID"] == "customer-api"
assert case.body["quantity"] == 2

# No call(), call_and_validate(), or HTTP client is invoked by bind_case().
```

`operation_cases(operation, scenario_strategy, bindings)` composes the two
strategies and yields `BoundSchemathesisCase(case, scenario)` values while
preserving the Scenario Engine replay context. It performs the same local
binding only.
