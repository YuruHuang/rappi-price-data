# Rappi tobacco and nicotine product study

This repository contains a point-in-time study of tobacco and nicotine products surfaced by Rappi
in Argentina, Colombia, Peru, and Mexico. It includes four country workbooks and the code,
configuration, and tests used to collect, classify, enrich, and export the observations.
The project is an independent research release and is not affiliated with or endorsed by Rappi.

## Published datasets

| Country | Workbook | Product observations | Store-location observations |
|---|---|---:|---:|
| Argentina | [`datasets/argentina.xlsx`](datasets/argentina.xlsx) | 2,325 | 59 |
| Colombia | [`datasets/colombia.xlsx`](datasets/colombia.xlsx) | 4,543 | 138 |
| Peru | [`datasets/peru.xlsx`](datasets/peru.xlsx) | 3,374 | 104 |
| Mexico | [`datasets/mexico.xlsx`](datasets/mexico.xlsx) | 597 | 18 |
| **Total** |  | **10,839** | **319** |

Each workbook has five sheets:

- `items`: one row per delivery location, store, and product;
- `stores`: store-level observation counts and product types;
- `locations`: the two configured delivery points;
- `summary`: country and category totals; and
- `data_dictionary`: definitions for every published field.

Checksums and file-level counts are in [`datasets/manifest.json`](datasets/manifest.json). Category
counts and interpretation notes are in [`datasets/README.md`](datasets/README.md).

## Study scope

The study covers four product families:

1. nicotine pouches;
2. electronic cigarettes, including disposable vapes, pods, and e-liquids;
3. heated tobacco products; and
4. cigarettes.

The six shared search terms were:

```text
bolsas de nicotina
cigarrillos electronicos
vapeador
vapeadores
productos de tabaco calentado
cigarrillos
```

Each country also used reviewed international and locally relevant brand searches. The exact terms,
brands, locations, and matching rules are versioned under [`config/study/`](config/study/) and
described in [`docs/methodology.md`](docs/methodology.md).

The collection used two public-landmark delivery points in each capital city. Results are therefore
a reproducible Rappi availability snapshot, not a national product census, sales ranking, market
share estimate, or legal-status assessment. A product visible at both locations or stores is kept as
separate observations so local price and availability are not collapsed.

## Use the datasets

No software is needed to inspect the four workbooks. Open a country file from `datasets/`; the
`summary` sheet opens first, and the `data_dictionary` explains the fields.

The observation key is:

```text
(country_code, zone_slug, store_id, product_id)
```

Prices are stored in local currency and identified by the `currency` column: ARS, COP, PEN, or MXN.

## Run the pipeline

Python 3.10 or newer is required.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

# Review the complete plan without network requests.
python -m rappi_co.study --all-countries --dry-run

# Collect, classify, and export one country.
python -m rappi_co.study --country ar

# Run the test suite.
python -m pytest tests -q
```

The complete/default run uses both configured locations and the full ordered query list. A different
query sequence or a location subset is labeled diagnostic and written outside the normal combined
output path. Collection stops on access challenges; it does not solve or bypass CAPTCHAs.

`--skip-collect` rebuilds only from a complete matching local raw archive. Historical raw responses
are not included in this GitHub release, so the four published workbooks are analytical outputs, not
a self-contained archive of the original API responses.

## Repository layout

```text
datasets/               four country workbooks and release manifest
config/study/            countries, delivery points, queries, and brand seeds
rappi_co/                collection, classification, enrichment, and export code
tests/                   automated regression and integrity tests
docs/                    methodology and country notes
```

## Data notes

- Rows describe products surfaced by Rappi at the sampled locations and collection time.
- All published observations were returned as available; unavailable or historical listings are not
  a complete part of this snapshot.
- Source prices are preserved. Extreme promotions or apparent merchant-entry errors should be
  flagged in price analyses rather than silently corrected.
- `confidence` describes the strength of the deterministic classification rule. It is not a
  statistical probability.
- Brand coverage is based on configured searches and source text; blank or unconfigured brands may
  remain, especially among electronic-cigarette products.

## License and source content

The software is provided under the repository [`LICENSE`](LICENSE). The workbooks reproduce factual
product observations from Rappi for research. No ownership of merchant names, product names, images,
or platform content is claimed. Confirm any institutional or source-platform requirements before
redistributing the data.
