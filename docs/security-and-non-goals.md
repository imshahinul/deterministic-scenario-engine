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

Phase 2 composition accepts bounded UTF-8 regular files beneath an explicit
local root. It rejects traversal components, absolute/URI/network paths,
backslashes, symlinks at every component, root escape, nonregular files, nested
composition, and portability case-fold collisions. YAML cannot dynamically
import Python or modules. Plugins and Python-packaged Domain Packs are explicit,
trusted, unsandboxed caller inputs; there is no automatic discovery or global
registry. No ambient current directory, home, environment search path, or locale
default becomes deterministic meaning.

## Explicit non-goals

Scenario Engine does not provide:

- an arbitrary Python DSL;
- arbitrary Python execution from YAML or dynamic YAML imports;
- arbitrary network execution or an API client;
- hidden network calls, network imports, remote composition, or network retrieval;
- automatic plugin or Domain Pack discovery, entry-point loading, filesystem
  scanning, or global plugin/Domain Pack registries;
- database-backed `ScenarioState`, ORM state, schema migration, or reflection-
  driven model discovery;
- ORM-owned state or a raw SQL DSL;
- unbounded loops or recursive subflows;
- hidden randomness, wall-clock semantic dependence, or implicit environmental state;
- automatic Schemathesis HTTP execution;
- indefinite replay across incompatible major contracts;
- a general-purpose sandbox, workflow engine, or database migration framework.
