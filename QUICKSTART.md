# Quick start

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

## Rebuild the final workbooks

The final four workbooks can be rebuilt offline from the integrated release:

```sh
python -m rappi_co.export.country_product_workbooks \
  --out data/country_products_rebuild
```

Choose a new output directory. The exporter checks its inputs and validates the
workbooks before writing the release.

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
