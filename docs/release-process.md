# Release process

The package README is the PyPI long description. It must describe durable
product and version semantics, not transient publication state. Statements such
as "unpublished", "no current-version tag", "no GitHub Release", or "no
package-index publication" belong only in checkpoint evidence, release audits,
or temporary release-candidate reports.

## Pre-RC

Before building artifacts:

- run the README release-state-neutrality test;
- require `PRE_RC_PYPI_LINK_PORTABILITY=PASS` by rejecting repository-relative
  file links in the package README and checking internal anchors separately;
- confirm the configured package long-description material passes the same
  neutrality test.

## RC

Release-candidate evidence may record that publication, a tag, or a release is
absent. Package long-description material may not encode those transient facts.

For the 3.0.0 candidate, qualify two independent fixed-`SOURCE_DATE_EPOCH`
builds from external `git archive` trees. Require byte-identical wheels and
sdists; verify metadata version 3.0.0, public Engine 2.0.0, historical Engine 1
1.0.0 evidence, licenses, dependencies, packaged release notes and DSL 2
reference, fixture inventories, and absence of secrets/host paths. Installed
consumers from wheel and sdist must pass on Python 3.11, 3.12, 3.13, and 3.14.
Retain the exact qualified bytes and SHA-256 identities; any source change
invalidates qualification.

## Pre-upload

Immediately before `twine upload`, rerun the source README neutrality test and
inspect the accepted wheel and sdist metadata to confirm their packaged
README/long description is release-state neutral. Require
`PREUPLOAD_PYPI_LINK_PORTABILITY=PASS` for both artifact descriptions, run
`twine check` and record `TWINE_RENDER_CHECK=PASS`, and resolve every important
absolute documentation target to record `PYPI_LINK_TARGET_CHECK=PASS`.

## Publication

Publish the exact accepted artifacts. Do not rebuild between acceptance and
publication.

Publication requires separate owner authorization. Before upload, confirm the
exact retained hashes, authentication configuration without exposing values,
absence of an existing release, and `twine check`. After upload, independently
compare PyPI hashes, install from the index, rerun smoke workflows, then create
only the separately authorized tag and GitHub Release. Candidate qualification
alone never authorizes authentication attempts, upload, tagging, or a release.

## Post-publication completion gate

Using fresh public observations rather than pre-upload text, verify:

- the PyPI version exists and its hashes exactly match the accepted artifacts;
- a production installation passes;
- the release tag targets the exact accepted commit;
- the GitHub Release exists and its asset hashes exactly match;
- the canonical README remains consistent with durable version semantics;
- package documentation still satisfies the release-state policy;
- fresh inspection of the rendered PyPI project page proves that documentation,
  examples, security, compatibility, license, and repository links resolve to
  their intended destinations, recording `POSTPUBLICATION_PYPI_LINK_SMOKE=PASS`.

`twine check` alone is not sufficient for link portability. The post-publication
gate must inspect the live PyPI description and its rendered link targets.

Only after every post-publication check passes may checkpoint evidence record
`PHASE_COMPLETE=YES`. A post-publication check must never rely solely on text
prepared before upload.

Published wheel and sdist metadata is immutable. If stale long-description text
has already shipped, record it as a known published-artifact limitation; do not
rewrite, rebuild, republish, or yank an otherwise accepted release merely to
alter that text. The durable correction applies to canonical `main` and future
artifacts.
