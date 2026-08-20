# Rappi tobacco and nicotine product study

This repository contains tobacco and nicotine product observations from Rappi in Argentina,
Colombia, Peru, and Mexico. It includes four country workbooks and the complete code used to collect,
classify, check, and export the data.

The project is an independent research release. It is not affiliated with or endorsed by Rappi.

## Published data

| Country | Workbook | Product observations | Store records by location |
|---|---|---:|---:|
| Argentina | [`datasets/argentina.xlsx`](datasets/argentina.xlsx) | 2,325 | 59 |
| Colombia | [`datasets/colombia.xlsx`](datasets/colombia.xlsx) | 4,543 | 138 |
| Peru | [`datasets/peru.xlsx`](datasets/peru.xlsx) | 3,374 | 104 |
| Mexico | [`datasets/mexico.xlsx`](datasets/mexico.xlsx) | 597 | 18 |
| **Total** |  | **10,839** | **319** |

The four product categories are:

1. nicotine pouches
2. electronic cigarettes, including disposable vapes, pods, and e liquids
3. heated tobacco products
4. cigarettes

The six main search terms are:

```text
bolsas de nicotina
cigarrillos electronicos
vapeador
vapeadores
productos de tabaco calentado
cigarrillos
```

Each country also has brand searches for reviewed international brands and brands relevant to the
local market. These are search seeds, not sales rankings. The exact brand queries are in
`config/study/brand_terms_ar.yml`, `brand_terms_co.yml`, `brand_terms_pe.yml`, and
`brand_terms_mx.yml`.

## What is inside each workbook

Each workbook contains five sheets.

| Sheet | Contents |
|---|---|
| `summary` | Country totals and totals for the four categories |
| `items` | The product observations and prices |
| `stores` | Store information and the number of observations from each store |
| `locations` | The two delivery points used in that country |
| `data_dictionary` | A plain language definition of every field |

The `summary` sheet opens first. The main data are in `items`.

One row in `items` represents one product from one store at one delivery location. The observation
key is:

```text
(country_code, zone_slug, store_id, product_id)
```

The same product can appear more than once when it is visible from different stores or locations.
This preserves the local price and availability information.

Prices remain in local currency. Check the `currency` field before comparing countries:

- Argentina: ARS
- Colombia: COP
- Peru: PEN
- Mexico: MXN

Workbook checksums and file counts are in [`datasets/manifest.json`](datasets/manifest.json).
Category counts and interpretation notes are in [`datasets/README.md`](datasets/README.md).

## Main file map

```text
rappi-tobacco-study/
|
|-- datasets/
|   |-- argentina.xlsx
|   |-- colombia.xlsx
|   |-- peru.xlsx
|   |-- mexico.xlsx
|   |-- manifest.json
|   `-- README.md
|
|-- config/
|   |-- keywords_co.yml
|   `-- study/
|       |-- countries.yml
|       |-- terms.yml
|       |-- zones_ar.yml
|       |-- zones_co.yml
|       |-- zones_pe.yml
|       |-- zones_mx.yml
|       |-- brand_terms_ar.yml
|       |-- brand_terms_co.yml
|       |-- brand_terms_pe.yml
|       `-- brand_terms_mx.yml
|
|-- rappi_co/
|   |-- study.py
|   |-- collect/
|   |   `-- search.py
|   |-- parsers/
|   |   |-- search_api.py
|   |   `-- store_payload.py
|   |-- classify/
|   |   |-- tobacco_classifier.py
|   |   |-- stage_c_overrides.py
|   |   `-- run.py
|   |-- enrich/
|   |   `-- tobacco_fields.py
|   `-- export/
|       `-- study_deliverable.py
|
|-- tests/
|-- docs/
|   |-- methodology.md
|   `-- countries/
|-- QUICKSTART.md
|-- requirements.txt
`-- LICENSE
```

The local team will normally work with these files:

| Task | File |
|---|---|
| Change the six shared search terms | `config/study/terms.yml` |
| Add or remove a brand search | `config/study/brand_terms_<country>.yml` |
| Change a delivery point | `config/study/zones_<country>.yml` |
| Change country name, city, currency, or domain | `config/study/countries.yml` |
| Change the shared Spanish classification words | `config/keywords_co.yml` |
| Review the search request and response parser | `rappi_co/parsers/search_api.py` |
| Review the collection loop | `rappi_co/collect/search.py` |
| Change product classification rules | `rappi_co/classify/` |
| Change nicotine, pack, or puff extraction | `rappi_co/enrich/tobacco_fields.py` |
| Change the CSV or Excel output | `rappi_co/export/study_deliverable.py` |
| Add a regression case | `tests/` |

The repository also keeps the earlier Colombia crawl modules for compatibility. They are not needed
for the four country search workflow described below.

## Set up the project

Python 3.10 or newer is required. Run the following commands from the repository root.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## Check the plan before collection

This command does not contact Rappi. It prints all eight locations, every query, and the total number
of requests.

```bash
python -m rappi_co.study --all-countries --dry-run
```

The complete plan contains two locations in each country. It uses 242 requests in total.

## Run a small collection check

Start with one simple query before running the full list.

```bash
python -m rappi_co.study --country ar --terms cigarrillos --collect-only
```

This runs the query at both configured Argentina locations and saves the raw result. It does not
classify or export a final workbook.

Check that both locations returned sensible products. If Rappi returns a CAPTCHA, challenge page, or
unexpected response, stop the run. The code does not bypass access controls.

## Run one complete country

Use the two letter country code: `ar`, `co`, `pe`, or `mx`.

```bash
python -m rappi_co.study --country ar
```

The program completes these steps:

1. It searches every configured term at both delivery locations.
2. It saves each raw response and writes a completion record.
3. It combines duplicate search results using `store_id` and `product_id`.
4. It classifies every product offline.
5. It keeps only the four study categories in the final output.
6. It writes CSV files, an Excel workbook, and a study manifest.

Run the other countries in the same way:

```bash
python -m rappi_co.study --country co
python -m rappi_co.study --country pe
python -m rappi_co.study --country mx
```

## Output files

A complete country run creates files under `data/<country>/`.

```text
data/<country>/
|
|-- raw/<location>/
|   |-- search_items_<time>.csv
|   |-- search_stores_<time>.csv
|   |-- search_manifest_<time>.json
|   `-- search_raw_<time>/*.json.gz
|
`-- processed/
    |-- <location>/classifications_<run_id>.csv
    `-- combined/
        |-- tobacco_items_<run_id>.csv
        |-- tobacco_stores_<run_id>.csv
        |-- locations_<run_id>.csv
        |-- tobacco_master_<run_id>.xlsx
        `-- study_manifest_<run_id>.json
```

The raw completion record lists the queries used at one location. The study manifest records the
exact input files, output files, row counts, file sizes, and checksums for the final country run.

The `data/` folder is ignored by Git. Do not force it into the repository. Raw responses can contain
platform metadata that is not needed in a public data release. After review, copy only the final
workbook intended for publication into `datasets/` and update `datasets/manifest.json`.

## Rebuild from saved raw files

Use this only when the complete raw files already exist on the same computer.

```bash
python -m rappi_co.study --country ar --skip-collect
```

The program accepts only a complete raw run whose ordered query list matches the current full plan.
It will not treat a small collection check as a complete country run.

The raw files used to create the four published workbooks are not included in this GitHub
repository. The repository contains the final analytical workbooks and the code needed to run a new
collection.

## Test changes

Run the tests before and after changing queries, rules, or export code.

```bash
python -m pytest tests -q
```

The release currently passes 281 tests, with one optional test skipped.

When adding a new classification rule, add examples that should be included and examples that should
be excluded. Then compare the new country output with the previous output before replacing a
published workbook.

## Interpretation limits

The collection used two public landmark delivery points in each capital city. The results describe
products surfaced by Rappi at those places and at that time. They are not:

- a national product census
- a sales or popularity ranking
- a market share estimate
- a complete list of unavailable products
- a legal status assessment

All published rows were returned as available. Source prices were preserved. Very large discounts or
apparent merchant entry errors should be flagged during price analysis instead of silently changed.

The `confidence` field describes the strength of a classification rule. It is not a probability.
Some brand fields remain blank when a brand was not configured or could not be read reliably from the
source text.

Read [`docs/methodology.md`](docs/methodology.md) for the complete method and the country notes under
[`docs/countries/`](docs/countries/) for the exact addresses and brand searches.

## License and source content

The software is provided under [`LICENSE`](LICENSE). The workbooks reproduce factual product
observations from Rappi for research. No ownership of merchant names, product names, images, or Rappi
content is claimed. Confirm institutional and source requirements before redistributing the data.
