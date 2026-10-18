# Rappi price data

Product-listing data collected from Rappi in Argentina, Colombia, Peru, and
Mexico. The release includes tobacco and nicotine products, sugar-sweetened
beverage (SSB) candidates, water, and alcohol from two delivery locations in
each country.

## 📦 Data release

The analysis-ready files are in
[`datasets/country_products/`](datasets/country_products/). Each workbook has
five worksheets: `Technical specifications`, `Tobacco products`, `SSBs`,
`Water`, and `Alcohol`.

| Country | Workbook | Rows | Currency |
| --- | --- | ---: | --- |
| Argentina | [argentina.xlsx](datasets/country_products/argentina.xlsx) | 17,556 | ARS |
| Colombia | [colombia.xlsx](datasets/country_products/colombia.xlsx) | 18,021 | COP |
| Peru | [peru.xlsx](datasets/country_products/peru.xlsx) | 18,322 | PEN |
| Mexico | [mexico.xlsx](datasets/country_products/mexico.xlsx) | 14,499 | MXN |
| **Total** |  | **68,398** |  |

One row represents a product listing at a store and delivery location at the
time of collection. The same product can therefore occur in more than one row.
The technical-specifications worksheet documents fields, units, collection
dates, and fields hidden from the default view.

## 🔎 Coverage and limits

Tobacco was collected on 16 August 2026 and beverages on 10 September 2026.
The two price waves are not contemporaneous.

The SSB worksheet is a screening cohort. Sweetening is unconfirmed for every
row, and this release does not contain quantitative sugar measurements. Blank
sugar values mean unknown, not zero. Alcohol by volume is retained only where
the listing supports it.

The dataset is a finite search at two delivery locations in each country. It
does not estimate the full Rappi catalogue, national availability, sales,
consumption, or market share. Raw beverage stock values are not verified
inventory counts. Product-detail pages are not included in the final
workbooks.

## 🗂️ Repository map

```text
datasets/
├── country_products/   analysis-ready country workbooks
├── integrated/         full release, including review and comparison records
├── beverages/          archived beverage source release
└── *.xlsx              archived tobacco source release
docs/
├── study_protocol.md   sample design, classification rules, and measurements
└── countries/          country-specific collection notes
rappi_co/               collection, classification, validation, and export code
tests/                  automated checks
config/                 search terms, delivery locations, and study settings
```

The integrated and country workbooks are alternative views of the same
observations. Do not append them to one another.

## ♻️ Reproduce the published release

Create an environment and install dependencies:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Rebuild the country workbooks from the archived integrated release:

```sh
python -m rappi_co.export.country_product_workbooks \
  --out data/country_products_rebuild
```

Use a new output directory. The exporter verifies source hashes, row counts,
identifiers, formulas, and output values before it writes the release.

Run the test suite with:

```sh
python -m pytest -q
```

## 🔄 Collect an updated release

The published `datasets/` directory is an archived September 2026 release. To
collect a new release for all four countries, inspect the configured search
plan and then run the update command:

```sh
python -m rappi_co.release_update --out data/updates/20261018 --dry-run
python -m rappi_co.release_update --out data/updates/20261018 --collect
```

The command writes verified country workbooks to
`data/updates/20261018/country_products/`. It preserves the archived release
and stops if Rappi returns a CAPTCHA or access challenge. If collection stops,
rerun the same command with `--resume`.

## 📌 Citation and contributions

Use [`CITATION.cff`](CITATION.cff) to cite the repository and release manifest.
See [`CONTRIBUTING.md`](CONTRIBUTING.md) to report an error or contribute a
reproducible update. Release changes are recorded in [`CHANGELOG.md`](CHANGELOG.md).

## 📄 License

The software is licensed under [`LICENSE`](LICENSE). The license does not
assert ownership of content supplied by Rappi or its merchants.
