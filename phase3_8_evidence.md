# Phase 3.8 — Deep Ecommerce Reference Evidence Workflow

## Entry baseline

- Branch: `main`
- HEAD: `6b02a869d458d3d6a5f374a539e5120b5bf9ac2f`
- Tree: `9b6c9c79025f013efbd46171b82ed52f2a694840`
- Parent: `74ce35da79ba7ae719bdb640f1704a0b2d9e3e68`
- Subject: `phase 3.7: add evidence interchange CLI`
- Local/remote divergence: `0/0`; staged/unstaged/untracked: `0/0/0`
- Tags: `1.0.0`, `2.0.0`; GitHub Releases: `1.0.0`, `2.0.0`; production PyPI: `2.0.0`
- Phase 2 release tag commit is an ancestor of the baseline.
- Distribution: `2.0.0`; engine: `1.0.0`; DSL: `1`; package-root exports: `33`
- CLI commands (12): `validate`, `run`, `replay`, `hash`, `inspect`, `explain`, `diff`, `matrix`, `batch`, `export`, `verify`, `migrate`
- Console entrypoint, dependencies, and `pyproject.toml` bytes matched accepted Phase 3.7.
- Phase 2 architecture SHA-256: `ca54465a88ee92cb6f14bbe4ecf03e709e31f33e724fcf07d7af9d6b0e42664e`
- Entry Phase 3 architecture SHA-256: `bea2fbe75bee1237266f854ad320a192d47510d1116cceee89c69c9bb3afaa8c`
- Entry schema inventory: `evidence.adapter-capability/1`, `evidence.adapter-receipt/1`, `evidence.adapter/1`, `evidence.bundle/1`, `evidence.compatibility-report/1`, `evidence.entry/1`, `evidence.fixture-index/1`, `evidence.migration-plan/1`, `evidence.provenance/1`, `evidence.relationship/1`
- No pre-existing Phase 3.8 implementation was found.

## Implemented reference identity

- Domain Pack: `ecommerce.reference_evidence@1`
- Domain Pack content SHA-256: `987651d083d7c87696ef10c377080e08a173a56bd64aa6114262e5f6e0c35bb6`
- Bundle ID: `db145c19d041ffbed668404a8945604e735d9db42c8f75068d657ba4a0c4c507`
- Bundle entries: 6; relationships: 4
- Baseline result SHA-256: `8715607e0f1978848f01c0c06ed57c1151934559465147cecc5274133396354a`
- Baseline manifest SHA-256: `533ca9f2d84f487af69fbcd4a768b2e60add3ed1ad4f5c16385d0e77fc86ab90`
- Baseline inspection SHA-256: `525761aa8b1bbac2724ec75530013884a032de2b561d4cd899b3fcb3591e148e`
- Oracle evaluation SHA-256: `ec820e86220674dbaa565904ba43b5679d2daf6f0e3d6b2e774e343d78e424b2`
- Variant result SHA-256: `fe921211be3f347c54a2837143a52fddf0099bdab9f6bf3bf925b913e9984695`
- Semantic diff SHA-256: `15f2133e6ca62af5dcf05790c2071d720d3a5a03d24a48085a201cac8a332469`

The runtime has no accepted Domain Pack coordinate mechanism, so
`manifest.domain_pack_versions` remains empty. The Domain Pack coordinate and
content hash stay explicit at the reference API/report boundary. No schema was
changed or added. `REFERENCE_FIXTURE_EXPORT_USED=NO`.

## Validation

- Focused regression: `89 passed, 8 subtests passed`
- Full regression: `601 passed, 144 subtests passed`
- Baseline replay normalized equality: pass
- Baseline replay exact byte equality: pass
- Repeated semantic diff bytes: pass
- Repeated fresh bundle exports complete file-map equality: pass
- In-process CLI JSON `verify`: pass and deterministic
- In-process CLI JSON `export`: pass; identity preserved; exported verification pass
- Existing 12-command CLI surface, package-root exports, versions, dependencies,
  existing ecommerce algorithms, and persisted schema inventory remain unchanged.

## Scope boundaries

No generic Domain Pack runner, automatic plugin registration/discovery, global
registry, new execution API, new evidence type/schema, migration example,
adapter, remote storage, network, credentials, environment input, database,
fixture abstraction, matrix/batch feature, release, or publication was added.
Phase 3.9 was not started.
