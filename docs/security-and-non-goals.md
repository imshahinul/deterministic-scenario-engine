# Security assumptions and non-goals

## YAML boundary

DSL 1 uses a safe YAML loader. It rejects custom/arbitrary tags, duplicate keys
at every mapping depth, aliases, and merge keys before semantic execution. This
reduces YAML ambiguity; it does not turn the engine into a general sandbox.

## Plugin trust boundary

**Plugins are Python code and are not sandboxed.**

The plugin API supplies explicit deterministic services and isolated arguments,
but it cannot make arbitrary malicious Python safe. Only trusted plugin code
should be registered. A conforming plugin must avoid hidden randomness, wall
clock, environment/process state, filesystem access, and network access.

## External I/O

Core deterministic execution must not depend on hidden network, filesystem, or
environment state. External values enter through supported explicit input and
resource boundaries. The core engine does not execute network requests.

The Schemathesis adapter only composes and binds local case objects; it does not
call cases or send HTTP requests. The caller or test framework owns any external
API execution.

The SQLAlchemy adapter performs transactional post-result materialization.
`ScenarioState` remains independent of the database; database contents are not
the deterministic state store.

## Explicit non-goals

Scenario Engine does not provide:

- an arbitrary Python DSL;
- arbitrary network execution or an API client;
- automatic plugin discovery, entry-point loading, filesystem scanning, or
  network retrieval;
- database-backed `ScenarioState`, ORM state, schema migration, or reflection-
  driven model discovery;
- unbounded loops or recursive subflows;
- hidden randomness or hidden wall clock;
- indefinite replay across incompatible major contracts;
- a general-purpose sandbox, workflow engine, or database migration framework.
