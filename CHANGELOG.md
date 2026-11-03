# Changelog

## Clean beverage workbooks

- Beverage-only country collections now write the clean `SSBs`, `Water`, and `Alcohol` tabs using the published country workbook's presentation, rather than copying the diagnostic workbook into `country_products/`.
- Added an offline command to format a completed beverage run without collecting again. It verifies source hashes, identities, and the exact SSB candidate membership, and preserves review and comparison records in the source files.

## Unreleased

- Added `python -m rappi_co.run` for fresh country-team collections with selected country, scope, locations, and query lists or files.
- Removed the fixed two-point limit for new collection profiles. Custom delivery lists support CSV, TSV, XLSX, JSON, and YAML with validated coordinates and stable location IDs.
- Added TXT, CSV, TSV, XLSX, JSON, and YAML search-term inputs to the country command.
- Extended the release, tobacco, beverage, and direct search commands to propagate custom locations through requests, location metadata, exports, and manifests.
- Added selected-country release packages, location-input snapshots, and resume checks that reject changed plans or configuration.
- Preserved the archived study data and reference location files; offline workbook reproduction is optional.

- Added resumable updated-release collection and exact workbook value checks.
- Kept the original published country term lists as the defaults, including
  country and brand queries. Term changes are optional per-run overrides.
- Retained the expanded beverage version 2 list in `config/archive/beverages_v2.yml`
  for optional use. The default `config/beverages.yml` matches version 1 used
  for the September release. Published data files are unchanged.
- Documented the beverage-term pilot, its coverage limits, and the procedure
  for testing, reviewing, and adopting future terms.
- Added a `--data-root` option for dated tobacco-term pilots and documented the
  tobacco search protocol in the README.

## 2026.09

- Published the archived tobacco and beverage release for Argentina, Colombia, Peru, and Mexico.
