# Rappi tobacco and nicotine product data

> [!IMPORTANT]
> **Status:** This is a private working repository. 

This repository contains four workbooks, one per country, and Python code for collecting,
classifying, checking, and exporting tobacco and nicotine product observations from Rappi in
Argentina, Colombia, Peru, and Mexico.

## 🚀 Start here

| Task | Command or file | Result |
|---|---|---|
| Open the included data | `datasets/<country>.xlsx` | Workbook with five sheets; Python is not needed |
| Preview every planned request | `python -m rappi_co.study --all-countries --dry-run` | JSON plan; no network use and no files written |
| Try one search term | `python -m rappi_co.study --country ar --terms cigarrillos --collect-only` | Raw files for both Argentina locations |
| Collect one country | `python -m rappi_co.study --country ar` | Raw files, classifications, CSV files, workbook, and manifests |
| Rebuild saved data | `python -m rappi_co.study --country ar --skip-collect` | New derived files without contacting Rappi |
| Check the code and workbooks | `python -m pytest tests -q` | Test report |

Valid country codes are `ar`, `co`, `pe`, and `mx`.

## 📦 Included workbooks

| Country | Workbook | Product observations | Store records by location |
|---|---|---:|---:|
| Argentina | [`datasets/argentina.xlsx`](datasets/argentina.xlsx) | 2,325 | 59 |
| Colombia | [`datasets/colombia.xlsx`](datasets/colombia.xlsx) | 4,543 | 138 |
| Peru | [`datasets/peru.xlsx`](datasets/peru.xlsx) | 3,374 | 104 |
| Mexico | [`datasets/mexico.xlsx`](datasets/mexico.xlsx) | 597 | 18 |
| **Total** |  | **10,839** | **319** |

Workbook checksums and file counts are in [`datasets/manifest.json`](datasets/manifest.json).
Category counts and interpretation notes are in [`datasets/README.md`](datasets/README.md).

## 🔎 What the collection covers

| Countries | Delivery locations | Product categories | Shared search terms | Planned requests |
|---:|---:|---:|---:|---:|
| 4 | 8 | 4 | 6 | 242 |

The four requested product categories are:

1. nicotine pouches
2. electronic cigarettes, including disposable vapes, pods, and e liquids
3. heated tobacco products
4. cigarettes

The six shared search terms are:

```text
bolsas de nicotina
cigarrillos electronicos
vapeador
vapeadores
productos de tabaco calentado
cigarrillos
```

Each country also has searches for reviewed international brands and brands relevant to the local
market. These are search seeds, not sales rankings. The exact brand queries are in:

```text
config/study/brand_terms_ar.yml
config/study/brand_terms_co.yml
config/study/brand_terms_pe.yml
config/study/brand_terms_mx.yml
```

## 📊 What is inside each workbook

Each workbook contains five sheets.

| Sheet | Contents |
|---|---|
| `summary` | Country totals and totals for the four categories |
| `items` | Product observations and prices |
| `stores` | Store information and observation counts |
| `locations` | The two delivery points used in that country |
| `data_dictionary` | A plain language definition of every field |

The `summary` sheet opens first. The main data are in `items`.

One `items` row represents one product from one store at one delivery location. The observation key
is:

```text
(country_code, zone_slug, store_id, product_id)
```

The same product can appear more than once when it is visible from different stores or locations.
This preserves local price and availability information.

A blank generally means that Rappi did not provide the value or that the pipeline could not derive
it reliably. A blank does not mean zero.

Prices remain in local currency. Check `currency` before comparing countries:

| Country | Currency |
|---|---|
| Argentina | ARS |
| Colombia | COP |
| Peru | PEN |
| Mexico | MXN |

## ▶️ Run the collection

### 1. Set up the project

Clone the private repository if it is not already on your computer:

```bash
git clone https://github.com/YuruHuang/rappi-tobacco-data.git
cd rappi-tobacco-data
```

You need access to the private GitHub repository before cloning it.

Create the Python environment from the repository root:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Python 3.10 or newer is required.

### 2. Preview the complete plan

```bash
python -m rappi_co.study --all-countries --dry-run
```

**What it does:** validates the four country configurations and prints the locations, queries,
currencies, request counts, and protocol status.

**What it creates:** nothing. This command does not contact Rappi.

The JSON output should show:

| Country | Locations | Queries | Requests | Protocol status |
|---|---:|---:|---:|---|
| Argentina | 2 | 27 | 54 | `full` |
| Colombia | 2 | 32 | 64 | `full` |
| Peru | 2 | 30 | 60 | `full` |
| Mexico | 2 | 32 | 64 | `full` |
| **Total** | **8** |  | **242** |  |

### 3. Try one search term

```bash
python -m rappi_co.study --country ar --terms cigarrillos --collect-only
```

**What it does:** sends one query at both configured Argentina locations.

**What it creates:** raw product, store, response, and collection manifest files. It does not create
a final workbook.

**What to check:** confirm that both locations returned sensible products. If Rappi returns a
CAPTCHA, challenge page, or unexpected response, stop the run. The code does not bypass access
controls.

### 4. Collect one complete country

```bash
python -m rappi_co.study --country ar
```

Replace `ar` with another country code when needed:

```bash
python -m rappi_co.study --country co
python -m rappi_co.study --country pe
python -m rappi_co.study --country mx
```

**What it does:**

1. searches every configured term at both delivery locations;
2. saves every raw response and writes a completion record;
3. combines duplicate search results within each location using `store_id` and `product_id`;
4. classifies every product offline;
5. keeps only the four requested product categories in the final data; and
6. writes CSV files, an Excel workbook, and a processed run manifest.

**What it creates:** the raw and processed files shown in the next section.

### How to read collection messages

| Message | Meaning |
|---|---|
| `[n/total] term +N new (T total)` | The query completed and added `N` new observation rows at that location |
| `+0 new` | No new unique rows were added; the response may contain products already found by earlier terms |
| HTTP 401 or 403 | The run stops immediately |
| HTTP 429 or a temporary server error | The request uses bounded retry and backoff |
| HTML or another response that is not JSON | The run treats it as a possible access challenge and stops |

### 5. Rebuild from saved raw files

```bash
python -m rappi_co.study --country ar --skip-collect
```

**What it does:** reruns classification and export without contacting Rappi.

**What it creates:** a new set of processed files linked to the exact complete raw run.

This works only when the complete raw files already exist on the same computer. The raw files used
for the included workbooks are not in this GitHub repository.

## 📁 What each run creates

A complete country run writes files under `data/<country>/`.

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

| File | Contents |
|---|---|
| `search_items_*.csv` | Products returned at one delivery location |
| `search_stores_*.csv` | Stores returned at one delivery location |
| `search_raw_*/*.json.gz` | One saved raw response per query |
| `search_manifest_*.json` | Exact location, ordered queries, and collection counts |
| `classifications_*.csv` | Every classified row, including excluded and review rows |
| `tobacco_items_*.csv` | Final observations in the four requested categories |
| `tobacco_stores_*.csv` | Store level observation counts |
| `locations_*.csv` | The two configured delivery points |
| `tobacco_master_*.xlsx` | Five sheet country workbook |
| `study_manifest_*.json` | Input and output paths, counts, sizes, and checksums for the processed run |

The `data/` folder is ignored by Git. Do not force it into the repository. Raw responses can contain
platform metadata that is not needed in the shared workbook folder.

## ⚙️ Change the collection

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
for this four country search workflow.

## 🗂️ Repository map

```text
rappi-tobacco-data/
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
|       |-- zones_<country>.yml
|       `-- brand_terms_<country>.yml
|
|-- rappi_co/
|   |-- study.py
|   |-- collect/
|   |-- parsers/
|   |-- classify/
|   |-- enrich/
|   `-- export/
|
|-- tests/
|-- docs/
|   |-- methodology.md
|   `-- countries/
|-- QUICKSTART.md
|-- requirements.txt
`-- LICENSE
```

## ✅ Check changes

Run the tests before and after changing queries, rules, or export code:

```bash
python -m pytest tests -q
```

The current repository passes 281 tests, with one optional test skipped.

When adding a classification rule, include examples that should be accepted and examples that should
be excluded. Compare the new country output with the previous output before replacing an included
workbook.

Replacing an included workbook is a maintainer task. After review, copy only the approved workbook
into `datasets/`, update its file size, checksum, and counts in `datasets/manifest.json`, and run:

```bash
python -m pytest tests/test_dataset_files.py -q
```

## ⚠️ Limits and responsible use

The collection used two public landmark delivery points in each capital city. The results describe
products surfaced by Rappi at those places and at that time. They are not:

- a national product census
- a sales or popularity ranking
- a market share estimate
- a complete list of unavailable products
- a legal status assessment

All included rows were returned as available. Source prices were preserved. Very large discounts or
apparent merchant entry errors should be flagged during price analysis instead of silently changed.

The `confidence` field describes the strength of a classification rule. It is not a probability.
Some brand fields remain blank when a brand was not configured or could not be read reliably from the
source text.

The workflow does not solve, bypass, or conceal CAPTCHAs or other access controls. Stop if an access
challenge appears.

Read [`docs/methodology.md`](docs/methodology.md) for the complete collection method and the country
notes under [`docs/countries/`](docs/countries/) for the exact addresses and brand searches.

## 📄 License and source content

The software is provided under [`LICENSE`](LICENSE). The workbooks contain factual product
observations collected from Rappi. No ownership of merchant names, product names, images, or Rappi
content is claimed. Confirm institutional and source requirements before redistributing the data.
