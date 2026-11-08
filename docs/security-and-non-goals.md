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

## Phase 3 evidence trust boundary

Evidence bundles are untrusted input. Core evidence construction, reading,
validation, compatibility reporting, and migration planning are local, bounded,
non-executing operations with no network, provider discovery, environment-driven
semantics, randomness, or wall-clock semantics. Reading a bundle never executes
child artifacts or Oracle Assertions. Unknown and future schemas fail closed.

Bundle paths are safe relative POSIX child paths. Traversal, absolute/URI paths,
backslashes, unsafe links, symlinks, and special files are rejected; reads and
aggregate work are bounded. Export, fixture creation, and migration require an
explicit absent destination and use atomic publication without overwrite.
Migrations select only a closed internal lossless transformation map, verify the
source hash, never dynamically import a route, and never accept an arbitrary
callable from data.

Python plugins, Python-packaged Domain Packs, and caller-supplied adapter objects
are explicit trusted participants and are **not sandboxed**. Adapters are never
automatically discovered. Adapter side effects belong to that trusted object,
not core evidence processing.

## Engine 2 reducer boundary

The module-qualified actor and input-list reducers execute locally and exclude
all plugin-dependent scenarios; trusted plugins elsewhere remain ordinary
unsandboxed Python. Reducers repeatedly execute trusted scenario code, so cost
and application side effects outside the deterministic state model remain the
caller's responsibility. Resource, source, evidence, coordinates, budgets, and
input trees are strictly validated and bounded. Input content may nevertheless
be sensitive. Raw input values are excluded from default representations and are
not logged by default, but callers control any surrounding logging and storage.

Reducer deadlines are cooperative checks between executions, not hard execution
timeouts. They cannot terminate blocked or non-returning code. Each accepted
candidate's own native Result/2 and Schedule/1 are authoritative and must replay
against that candidate; the original schedule is not evidence for changed source
or inputs. Outcome summaries are noncanonical convenience objects, not
tamper-proof evidence. `SOURCE_ANCHORED_SINGLE_INVARIANT_SIGNATURE` is a
restricted preservation predicate, not independent proof of general semantic
equivalence. Minimality is conditional on a complete final one-deletion pass and
never claims a global minimum.

## Explicit non-goals

Scenario Engine does not provide:

- an arbitrary Python DSL;
- arbitrary Python execution from YAML or dynamic YAML imports;
- arbitrary network execution or an API client;
- hidden network calls, network imports, remote composition, or network retrieval;
- automatic plugin or Domain Pack discovery, entry-point loading, filesystem
  scanning, adapter/provider discovery, or global plugin/Domain Pack registries;
- database-backed `ScenarioState`, ORM state, schema migration, or reflection-
  driven model discovery;
- ORM-owned state or a raw SQL DSL;
- unbounded loops or recursive subflows;
- hidden randomness, wall-clock semantic dependence, or implicit environmental state;
- automatic Schemathesis HTTP execution;
- indefinite replay across incompatible major contracts;
- recursive or lossy migration;
- remote artifact retrieval in core evidence processing;
- distributed scheduling, workers, services, or orchestration;
- a general-purpose sandbox, workflow engine, or database migration framework;
- plugin execution, hard termination, general-purpose minimization, or global
  optimality from the restricted Engine 2 reducers.
