# Release process

The package README is the PyPI long description. It must describe durable
product and version semantics, not transient publication state. Statements such
as "unpublished", "no current-version tag", "no GitHub Release", or "no
package-index publication" belong only in checkpoint evidence, release audits,
or temporary release-candidate reports.

## Pre-RC

Before building artifacts:

- run the README release-state-neutrality test;
- confirm the configured package long-description material passes the same
  neutrality test.

## RC

Release-candidate evidence may record that publication, a tag, or a release is
absent. Package long-description material may not encode those transient facts.

## Pre-upload

Immediately before `twine upload`, rerun the source README neutrality test and
inspect the accepted wheel and sdist metadata to confirm their packaged
README/long description is release-state neutral.

## Publication

Publish the exact accepted artifacts. Do not rebuild between acceptance and
publication.

## Post-publication completion gate

Using fresh public observations rather than pre-upload text, verify:

- the PyPI version exists and its hashes exactly match the accepted artifacts;
- a production installation passes;
- the release tag targets the exact accepted commit;
- the GitHub Release exists and its asset hashes exactly match;
- the canonical README remains consistent with durable version semantics;
- package documentation still satisfies the release-state policy.

Only after every post-publication check passes may checkpoint evidence record
`PHASE_COMPLETE=YES`. A post-publication check must never rely solely on text
prepared before upload.

Published wheel and sdist metadata is immutable. If stale long-description text
has already shipped, record it as a known published-artifact limitation; do not
rewrite, rebuild, republish, or yank an otherwise accepted release merely to
alter that text. The durable correction applies to canonical `main` and future
artifacts.
