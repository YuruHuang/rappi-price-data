# Collect fresh Rappi listings for your country

Country teams can collect new listings for their own delivery points and search lists with `python -m rappi_co.run`. The command supports any positive number of valid locations. The published study's two points per city are defaults, not a restriction on a custom collection. Start with a dry run, inspect the planned searches, and then collect into a fresh output folder.

The files under `config/examples/` demonstrate supported input structures. Their location records reproduce public landmarks from the study profiles; they do not establish current delivery coverage. The short example term lists demonstrate the workflow and are not complete research protocols.

## Get the code and activate Python

In a new macOS zsh terminal, check the prerequisites:

```zsh
git --version
python3 --version
```

Choose an existing parent folder in Finder, drag it into Terminal after typing `cd `, and press Return. Then obtain your first working copy:

```zsh
git clone https://github.com/YuruHuang/rappi-price-data.git
cd rappi-price-data
```

The private repository requires a GitHub account with access and working Git authentication. Resolve an authentication failure before continuing. Do not enter credentials into a recorded command or a clone URL.

If you already have a checkout, enter its folder instead. Check local changes before updating; preserve your changes if the status is not clean:

```zsh
git status
git pull --ff-only
```

From the project root, where `requirements.txt` is located, create and activate an environment:

```zsh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m rappi_co.run --help
```

Create the environment once. In later terminal sessions, enter the project folder and run `source .venv/bin/activate` again. `python -m pip` installs into that active Python environment. The main collection uses `httpx`; the optional Scrapy browser stack is unnecessary for these commands.

## Prepare your delivery locations

Copy `config/examples/locations_co.csv` to your own filename and edit it in a text editor or spreadsheet application. Use as many rows as the study needs. Every record requires a full `address`, numeric `lat`, and numeric `lng`. Coordinates must already be checked by your team: this code does not geocode an address or confirm Rappi delivery coverage.

Use a unique stable `slug` for each point. It may contain letters, numbers, hyphens, and underscores and must start with a letter or number. If omitted, the loader generates one from the address and coordinates. Explicit slugs make comparison and review easier. `city` and `district` are optional; providing them helps interpret the output.

Supported location files are CSV, TSV, XLSX, JSON, YAML, and YML. XLSX reads the first worksheet, with headers in its first row. JSON and YAML accept a list of location records or a mapping containing `locations` or `zones`. Equivalent Colombia examples are supplied in CSV, YAML, and JSON.

For a single country, `country_code` can be omitted: `--country co` supplies the collection scope. Tagged rows for other countries are validated and filtered out. For a file used across several countries, tag every row with `ar`, `co`, `pe`, or `mx`. See `config/examples/locations_multi_country.csv`. A requested country must have at least one matching point. The entire file is validated before collection, including rows outside the selected country.

Add a row to include a point; remove a row from a new input version to exclude it. There is no `active` switch. Preserve the previous input file when coverage changes. Changing an address or coordinates changes the observation context, so record why the change was made.

## Prepare your search lists

The original country lists used for the published data are the default. Leave out all term options to keep them. Tobacco combines `config/study/terms.yml` with `config/study/brand_terms_<code>.yml`. Beverages combine `categories`, `regional_terms.<code>`, and `brand_queries.<code>` from `config/beverages.yml`. Changing the location file does not drop general, brand, or country-specific terms. The remaining steps in this section are optional.

To edit terms, copy the complete country lists from `config/examples/terms/`. For Colombia on a Mac:

```zsh
mkdir -p inputs
cp config/examples/terms/co_tobacco.csv inputs/co_tobacco_full_terms.csv
cp config/examples/terms/co_beverages.csv inputs/co_beverages_full_terms.csv
open -e inputs/co_beverages_full_terms.csv
```

Choose filenames beginning with `ar`, `co`, `pe`, or `mx` for the country you need. Keep the `term` header, then add rows or delete only the queries you mean to remove. For both topics, supply the copies with `--tobacco-terms-file inputs/co_tobacco_full_terms.csv --beverage-terms-file inputs/co_beverages_full_terms.csv`. Run another dry run to check the complete resulting list before collecting. If you already have edited copies, use new filenames before copying again.

The files `config/examples/tobacco_terms.txt` and `config/examples/beverage_terms.csv` contain only two queries each and demonstrate file formats. They are not the full study lists. TXT uses one query per nonblank line. CSV, TSV, and the first XLSX worksheet require a `term`, `query`, or `search_term` column. JSON and YAML accept a string list or a `terms` or `queries` list.

A supplied list **replaces** the configured search queries for its topic; it does not add to them. Include every query you want searched. To remove a query, omit it from the new list. Exact duplicate strings are removed, but spellings and capitalization are otherwise retained. A query containing a comma remains one query when stored correctly in a file.

These files control discovery. They do not rewrite classification rules or turn every returned product into an included tobacco product or confirmed SSB. New product families may need separate classification review. If no term file is supplied, that topic uses the repository's configured query plan. If no location file is supplied, the selected country uses its configured study locations.

Default query counts per point are tobacco/beverage: Argentina 27/45, Colombia 32/44, Peru 30/44, and Mexico 32/45. The default beverage lists match the published September query lists exactly. The later expanded list is preserved separately in `config/archive/beverages_v2.yml` and is not loaded automatically.

## Inspect the collection plan

This example searches Colombia using the two supplied points and the full country lists:

```zsh
python -m rappi_co.run --country co \
  --locations-file config/examples/locations_co.csv \
  --scope both \
  --out data/updates/co_20261103_demo \
  --dry-run
```

The dry run makes no network requests. Check `country_code`, the address records, each topic's `queries`, and `planned_search_requests`. This example plans 152 searches: two points multiplied by 32 tobacco and 44 beverage queries. Retries can add requests during collection. The printed input hashes identify the supplied files. Choose a new descriptive output directory for each real wave; the date in this example is illustrative.

## Collect and retain the new wave

After reviewing the plan, repeat the same arguments with `--collect`:

```zsh
python -m rappi_co.run --country co \
  --locations-file config/examples/locations_co.csv \
  --scope both \
  --out data/updates/co_20261103_demo \
  --collect
```

Requests run sequentially with default delays of one to three seconds. `--min-delay` and `--max-delay` allow longer pacing, for example `--min-delay 3 --max-delay 6`. Keep the input files unchanged while collection runs. The output directory must be new. Keep each wave separately rather than writing into `datasets/`.

For an interrupted `--scope both` collection, repeat its original command, inputs, output directory, and `--collect`, adding `--resume`. Resume checks the saved plan and rejects changed locations, queries, or configuration. Single-topic collections do not support resume through this wrapper; retain the failed run for diagnosis and choose a new folder for the next attempt.

## Collect one topic or several countries

For only beverages with all configured country terms, use `--scope beverages`:

```zsh
python -m rappi_co.run --country co \
  --locations-file config/examples/locations_co.csv \
  --scope beverages \
  --out data/updates/co_beverages_20261103_demo \
  --dry-run
```

Use `--scope tobacco` for tobacco alone. A single-topic run can filter points with repeatable `--address SLUG` options. For `--scope both`, put exactly the intended points into the supplied locations file. Do not combine `--terms-file` with the topic-specific terms-file option; for both topics use their separate files.

For several countries, the lower-level release command accepts repeated country selections:

```zsh
python -m rappi_co.release_update \
  --country co --country mx \
  --locations-file config/examples/locations_multi_country.csv \
  --out data/updates/co_mx_20261103_demo \
  --dry-run
```

This uses configured terms for both topics. Omit country flags only when all four countries are intended. Review the plan before replacing `--dry-run` with `--collect`.

## Review before sharing

For both topics, review `manifest.json`, `update_state.json`, `inputs/`, and the workbook under `country_products/`. Keep `raw/tobacco/` and `raw/beverages/`, which contain source responses, search manifests, and derived topic outputs. Review beverage audit, query-yield, coverage, and review records as well as the final workbook. For a single topic, the wrapper writes `plan.json`, `inputs/`, `source/`, `manifest.json`, and a topic workbook under `country_products/`; a failure writes `FAILED.json`.

A completed package checks source hashes, row identities, category partitions, and workbook contents. Human review still matters: examine unexpected zero results, irrelevant products, duplicate sightings, capped store groups, and uncertain classification. A row describes a listing at a sampled place and time. It does not establish sales, national availability, or confirmed sugar content.
