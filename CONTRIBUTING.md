# Contributing

Report data or documentation errors through an issue with the affected file,
country, worksheet, row identifier, and supporting evidence. Do not overwrite
archived releases. New collections must be written to a dated directory under
`data/updates/` and retain their manifests and source hashes.

Before opening a pull request, run `python -m pytest -q` and do not commit
cookies, access tokens, browser state, or local collection output.

For a new beverage discovery term, first run a dated pilot at both configured
locations and inspect its query-yield and coverage reports. Add only terms with
a documented target family and review result. Update `config/beverages.yml`,
its version, the changelog, and the study protocol together. Do not revise an
archived release to reflect a later search plan.
