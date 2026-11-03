# Quick start

## Collect fresh data for your country

Use Python 3.12 for the tested setup. After cloning the repository, run from its root:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m rappi_co.run --country co \
  --locations-file config/examples/locations_co.csv \
  --scope both \
  --out data/updates/co_MY_RUN --dry-run
```

This command keeps the original country queries used for the published data, including general words, local wording, and brand searches. No terms file is needed unless you choose to change the searches. The two-query term files in `config/examples/` are format examples, not the full lists. Your location file can contain any positive number of delivery points. CSV, TSV, XLSX, JSON, and YAML are accepted. Each point needs an address and numeric latitude/longitude. The examples include known public landmarks; add the checked points required by your team. A new country beyond ar/co/pe/mx still requires country-service configuration and code support.

After reviewing the printed plan, replace `--dry-run` with `--collect`. Do not create the output directory first. Open the workbook under `data/updates/co_MY_RUN/country_products/`. Use a new run label for later collections. `--resume` is available for interrupted `--scope both --collect` runs with the original inputs.

To use just beverages:

```sh
python -m rappi_co.run --country co --scope beverages \
  --locations-file config/examples/locations_co.csv \
  --out data/updates/co_beverages_MY_RUN --dry-run
```

This also keeps the full country's beverage terms. Custom lists are optional and replace the default list for that run. To add terms without dropping the existing country and brand queries, first export the full list as shown in [the detailed country team guide](docs/country_team_guide.md#prepare-your-search-lists), then edit the copy. Use `--terms-file` for TXT, CSV, TSV, XLSX, JSON, or YAML queries.

After a beverage-only collection, open `country_products/co_beverages.xlsx` inside your run folder. It has three clean tabs: `SSBs`, `Water`, and `Alcohol`. Review and diagnostic tables remain separately in `source/`.

If you already collected beverages with an older version and got tabs such as `summary` and `items`, format that saved run with:

```sh
python -m rappi_co.export.beverage_workbook --run-dir data/updates/co_demo_02
```

Open `data/updates/co_demo_02/country_products/co_beverages_clean.xlsx`. No collection is repeated. The original workbook is retained. Change the run folder to match your own run; use `--out PATH.xlsx` if the default clean filename already exists.

Tobacco-only runs also create the clean presentation, with `Technical specifications` and `Tobacco products`. Runs using `--scope both` create the same five tabs as the published country workbooks. No separate formatting command is needed for a new collection.

To format an older saved tobacco or combined run without collecting again:

```sh
python -m rappi_co.export.product_workbook --run-dir data/updates/YOUR_RUN
```

The new file ends in `_clean.xlsx` and keeps the original output. The same command also accepts beverage-only runs.

## Existing published files

The final files are in [`datasets/country_products/`](datasets/country_products/).
There is one workbook for each country, and every workbook has the same five
worksheets:

1. `Technical specifications`
2. `Tobacco products`
3. `SSBs`
4. `Water`
5. `Alcohol`

Python is not needed to open or analyze the published Excel files.

## Install the pipeline

From the repository root:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## Optional rebuild of historical workbooks

The final four workbooks can be rebuilt offline from the integrated release:

```sh
python -m rappi_co.export.country_product_workbooks \
  --out data/country_products_rebuild
```

Choose a new output directory. The exporter checks its inputs and validates the
workbooks before writing the release. This is useful for auditing or reformatting saved data and does not refresh prices.

## Collect updated country workbooks

The published `datasets/` files are a frozen release. To create a new dated
release for all four countries, review the planned searches and then collect:

```sh
python -m rappi_co.release_update --out data/updates/20261017 --dry-run
python -m rappi_co.release_update --out data/updates/20261017 --collect
```

The verified updated workbooks are written to
`data/updates/20261017/country_products/`. This command does not overwrite the
frozen `datasets/` release. Stop collection if Rappi returns a CAPTCHA or
access challenge.

## Review a collection plan

Dry runs show the requests without contacting Rappi:

```sh
python -m rappi_co.study --all-countries --dry-run
python -m rappi_co.beverages --all-countries --dry-run
```

Valid country codes are `ar`, `co`, `pe`, and `mx`. To collect or rebuild one
country with the original tobacco workflow:

```sh
python -m rappi_co.study --country ar
python -m rappi_co.study --country ar --skip-collect
```

To run the beverage workflow for all four countries:

```sh
python -m rappi_co.beverages --all-countries
python -m rappi_co.beverages --all-countries --skip-collect
```

The rebuild commands require raw files previously produced by the same
pipeline. Stop collection if the site returns a CAPTCHA or access challenge.

## Run the tests

```sh
python -m pytest -q
```

See the [study protocol](docs/study_protocol.md) for the sample design,
classification rules, measurements, and limitations.
