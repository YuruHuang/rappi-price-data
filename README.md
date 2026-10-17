# Rappi tobacco and beverage data

This repository contains product listings collected from Rappi in Argentina,
Colombia, Peru, and Mexico. The study covers tobacco and nicotine products,
sugar-sweetened beverage candidates, water, and alcohol at two delivery
locations in each country.

## Final workbooks

Use the country workbooks in [`datasets/country_products/`](datasets/country_products/)
for analysis. Each workbook has the same five worksheets:

1. `Technical specifications`
2. `Tobacco products`
3. `SSBs`
4. `Water`
5. `Alcohol`

| Country | Workbook | Observations | Currency |
| --- | --- | ---: | --- |
| Argentina | [argentina.xlsx](datasets/country_products/argentina.xlsx) | 17,556 | ARS |
| Colombia | [colombia.xlsx](datasets/country_products/colombia.xlsx) | 18,021 | COP |
| Peru | [peru.xlsx](datasets/country_products/peru.xlsx) | 18,322 | PEN |
| Mexico | [mexico.xlsx](datasets/country_products/mexico.xlsx) | 14,499 | MXN |
| **Total** |  | **68,398** |  |

The first worksheet explains the sample, dates, units, field coverage, and
limitations. The product worksheets open with category measures and selected
source context. Additional raw source fields, measurement evidence, and
provenance are grouped in hidden columns at the right and can be unhidden in
Excel. The first worksheet marks every field as shown or hidden.

## Interpretation

One row represents a product listing from one store, delivery location, and
collection time. The same product may appear in more than one row when it was
offered by different stores or at different locations.

Tobacco was collected on 16 August 2026. Beverages were collected on
10 September 2026. Prices from the two collection waves are therefore not
contemporaneous.

The `SSBs` worksheets contain a screening cohort; sweetening is unconfirmed for
every row. The current release has no quantitative sugar measurements, so blank
sugar cells mean unknown, not zero. Alcohol indicators and alcohol by volume
are shown as cross-category checks for candidates that may require review. ABV
is populated only when supported by listing evidence.

The beverage source did not provide a validated row-level brand field, so
beverage brands were not inferred from product titles. Brand examples in the
Technical specifications sheet document search coverage only. Availability is
a normalized listing status at collection; hidden raw beverage stock values are not
verified inventory counts.

The data come from a finite search at two delivery locations per country. They
do not represent a complete Rappi catalog, national availability, sales,
consumption, or market share. Product-detail pages are not part of the final
workbooks.

## Other data layouts

- [`datasets/integrated/`](datasets/integrated/) contains the full 95,688-row
  release, including comparison, review, and excluded beverage records.
- [`datasets/beverages/`](datasets/beverages/) contains the original beverage
  source workbooks.
- [`datasets/`](datasets/) contains the original tobacco source workbooks.

These directories provide alternative views or source releases. Do not append
them to the final country workbooks as if they were additional observations.

## Rebuild and test

Create a Python environment from the repository root:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Rebuild the final country workbooks from the integrated release:

```sh
python -m rappi_co.export.country_product_workbooks \
  --out data/country_products_rebuild
```

The destination must be new. The exporter works offline and verifies source
hashes, row counts, identifiers, formulas, and output values before publishing.

Run the tests with:

```sh
python -m pytest -q
```

## Collect an updated four-country release

The published files above are a frozen September 2026 release. To collect a
new release without changing those files, first review the exact four-country
search plans, then run the dated update command:

```sh
python -m rappi_co.release_update --out data/updates/20261017 --dry-run
python -m rappi_co.release_update --out data/updates/20261017 --collect
```

The command writes four updated country workbooks to
`data/updates/20261017/country_products/` and publishes a manifest only after
it verifies source hashes, identities, SSB-candidate membership, category
partitions, and workbook integrity. It never overwrites the frozen
`datasets/` release. Stop collection if Rappi returns a CAPTCHA or access
challenge.

The concise collection and classification method is documented in
[`docs/study_protocol.md`](docs/study_protocol.md). Exact file hashes and counts
are recorded in the manifests beside each release.

## License

The repository software is licensed under the terms in [`LICENSE`](LICENSE).
That license does not assert ownership of source-platform or merchant content.
