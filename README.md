# Rappi price data

This repository contains Rappi product-listing data and the code used to collect it. The study covers tobacco and nicotine products, water, alcohol, and beverage candidates for review as sugar-sweetened beverages (SSBs) in Argentina, Colombia, Peru, and Mexico.

## For country teams

The main task is to collect fresh listings for **your country, your delivery points, and your search terms**. Start with the [country team guide](docs/country_team_guide.md) or [quick start](QUICKSTART.md).

There is no fixed delivery-point count. Supply a CSV, TSV, XLSX, JSON, or YAML file using `--locations-file`. At minimum each row needs `address`, `lat`, and `lng`; include `slug` for a stable location ID and optionally `city`, `district`, and `country_code`. Coordinates must be supplied; the collector does not geocode street addresses. For example:

```sh
python -m rappi_co.run --country co \
  --locations-file config/examples/locations_co.csv \
  --scope both \
  --out data/updates/co_MY_RUN --dry-run
```

This keeps the original country lists used for the published data, including generic, local, and brand queries. Changing delivery points does not change those terms. The two-query files in `config/examples/` show input formats; they are not the full study lists. Review the location list, exact queries, and request count. Replace `--dry-run` with `--collect` to make requests and create a new package. The default pacing is a random one to three seconds between sequential searches. Use a new output directory for every new run; do not create it manually first. For a both-scope collection, the workbook is written under `country_products/` in your output directory.

For one product scope, use `--scope tobacco` or `--scope beverages`; omit term options to keep all configured queries for that topic. Custom terms are optional: `--terms "query one,query two"` or `--terms-file PATH` replaces the full list for that run. Terms files support TXT, CSV, TSV, XLSX, JSON, and YAML. To add a term while keeping existing searches, start from the full country list as shown in the [country team guide](docs/country_team_guide.md#prepare-your-search-lists). A new search word does not automatically add a classification rule.

### Reference locations and shared default terms

The following points document the archived study and remain the defaults when no custom file is supplied. Country teams can use their own list without editing these reference files. Keep the selected list stable during a run and retain its snapshot and manifest with the data.

### 1. Confirm the delivery points

The archived study sampled two points per city. That historical sample size is not a limit on new collections.

| Country | City | Delivery points | Details |
| --- | --- | --- | --- |
| Argentina | Buenos Aires | Galerías Pacífico; Alto Palermo | [country note](docs/countries/argentina.md) |
| Colombia | Bogotá | Plaza Bolívar; Andino | [country note](docs/countries/colombia.md) |
| Peru | Lima | Larcomar; MegaPlaza | [country note](docs/countries/peru.md) |
| Mexico | Mexico City | Bellas Artes; Perisur | [country note](docs/countries/mexico.md) |

Each country note gives the address, district, coordinates, and tobacco collection context. The source files are [`config/study/zones_ar.yml`](config/study/zones_ar.yml), [`zones_co.yml`](config/study/zones_co.yml), [`zones_pe.yml`](config/study/zones_pe.yml), and [`zones_mx.yml`](config/study/zones_mx.yml).

For a custom collection, add or remove rows in your location input, review the dry run, and collect into a new output directory. If changing the shared reference sample, update the zone file, country note, and protocol documentation as well.

### 2. Review the terms

Run a dry run first. It makes no network requests and prints all selected locations and every tobacco and beverage query. The older command below still plans all four countries using the defaults; add `--country co` and `--locations-file PATH` to select a custom country collection.

```sh
python -m rappi_co.release_update --out data/updates/YYYYMMDD --dry-run
```

Check the country, locations, query count, and terms before collecting. The lists are deliberately finite; a zero result does not show that a product is absent from the country.

- Tobacco: shared terms are in [`config/study/terms.yml`](config/study/terms.yml); country brand queries are in `config/study/brand_terms_<country>.yml`.
- Beverages: shared categories, country terms, and brand queries are in [`config/beverages.yml`](config/beverages.yml).

### 3. Test a proposed change

Use a dated pilot directory. The command searches both configured locations but does not alter the archived release.

```sh
# Tobacco
python -m rappi_co.study --country mx --terms "new term" \
  --data-root data/pilots/tobacco_term_check_YYYYMMDD

# Beverages
python -m rappi_co.beverages --country mx --terms "new term" \
  --data-root data/pilots/beverage_term_check_YYYYMMDD
```

For each pilot, review the returned product families, duplicate results, and capped store groups. For beverages, also review `beverage_query_yield_*.csv`, `beverage_coverage_*.csv`, and the review workbook. Keep a term only when it finds a relevant product family not already well covered by the existing list.

Add a generic tobacco term to `config/study/terms.yml` and a brand term to the relevant country file. For beverages, add a generic term to `categories`, a country term to `regional_terms`, or a brand search to `brand_queries`. Record the change in the country note, study protocol, and changelog. A changed term list is a new protocol, not a revision to an archived release.

### 4. Run and check a new release

The update command below collects all four countries using shared defaults. Country teams normally use `rappi_co.run --country CODE` as shown above. The lower-level update command also accepts repeated `--country`, `--locations-file`, `--tobacco-terms`, and `--beverage-terms`.

```sh
python -m rappi_co.release_update --out data/updates/YYYYMMDD --collect
```

Do not write into `datasets/`. If the run stops, use the same output directory:

```sh
python -m rappi_co.release_update --out data/updates/YYYYMMDD --collect --resume
```

Before sharing the result, check the run's `manifest.json`, the selected country workbooks in `country_products/`, and the source manifests. Resume only with the same inputs; changed locations, queries, or configuration are rejected. The update command checks source hashes, row identities, category partitions, and workbook contents; it stops when Rappi returns an access challenge.

## Published data

[`datasets/country_products/`](datasets/country_products/) contains one analysis-ready workbook per country. Each workbook has `Technical specifications`, `Tobacco products`, `SSBs`, `Water`, and `Alcohol` sheets.

| Country | Workbook | Rows | Currency |
| --- | --- | ---: | --- |
| Argentina | [argentina.xlsx](datasets/country_products/argentina.xlsx) | 17,556 | ARS |
| Colombia | [colombia.xlsx](datasets/country_products/colombia.xlsx) | 18,021 | COP |
| Peru | [peru.xlsx](datasets/country_products/peru.xlsx) | 18,322 | PEN |
| Mexico | [mexico.xlsx](datasets/country_products/mexico.xlsx) | 14,499 | MXN |
| **Total** |  | **68,398** |  |

One row is one product listing from one store at one delivery point at one collection time. Products can therefore appear in more than one row. Field definitions and collection dates are in each workbook's `Technical specifications` sheet.

Tobacco was collected on 16 August 2026; beverages were collected on 10 September 2026. Do not treat the two waves as contemporaneous. The SSB sheet is a screening set: sugar is unconfirmed for every row, and blank sugar fields mean unknown. The data describe listings at the sampled points, not national availability, sales, consumption, market share, or verified inventory.

## Current search plans

The archived tobacco release covers nicotine pouches, electronic cigarettes, heated tobacco, and cigarettes. It used six shared Spanish terms plus country-specific brand searches: 27 queries in Argentina, 32 in Colombia, 30 in Peru, and 32 in Mexico. The complete country lists and collection notes are in [`docs/countries/`](docs/countries/).

The default beverage plan in [`config/beverages.yml`](config/beverages.yml) is version 1, the same query list used for the published September data. Changing terms is optional; copy the full country list, edit the copy, and pass it with a terms-file option as described in the country team guide.

The later expanded version is retained separately at [`config/archive/beverages_v2.yml`](config/archive/beverages_v2.yml). It is not loaded by default. It adds:

- Argentina: `bebida lactea`, `limonada`, `cafe frio`, `vermut`, `aperitivo`
- Colombia: `bebida lactea`, `bebida de malta`, `limonada`, `cafe frio`, `hard seltzer`
- Peru: `bebida lactea`, `limonada`, `cafe frio`, `hard seltzer`, `bebida preparada`
- Mexico: `bebida lactea`, `horchata`, `cafe frio`, `pulque`, `hard seltzer`

The 40-search pilot completed in October 2026. It confirmed that the new terms returned listings, not that they provide complete coverage or identify SSBs. Teams can choose to add those terms to their own copies. The original version-1 configuration is also retained at [`config/archive/beverages_v1.yml`](config/archive/beverages_v1.yml).

## Repository map

```text
datasets/
├── country_products/   analysis-ready country workbooks
├── integrated/         full release, review records, and comparison records
├── beverages/          archived beverage release
└── *.xlsx              archived tobacco release
docs/
├── study_protocol.md   study design and classification rules
└── countries/          country collection notes
config/                 search terms, delivery points, and settings
rappi_co/               collection, classification, validation, and export code
tests/                  automated checks
```

The integrated and country workbooks contain the same observations in different formats. Do not append them together.

## Optional reproduction of the published workbooks

This reproduces the historical release for auditing or reprocessing; it does not collect fresh prices. Country teams collecting new data should use the country command above.

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m rappi_co.export.country_product_workbooks \
  --out data/country_products_rebuild
python -m pytest -q
```

Use a new output directory. The exporter checks source hashes, row counts, identifiers, formulas, and written values.

## Citation, contributions, and license

Use [`CITATION.cff`](CITATION.cff) to cite the repository and release manifest. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for corrections or reproducible updates, and [`CHANGELOG.md`](CHANGELOG.md) for release changes. The software license is in [`LICENSE`](LICENSE); it does not claim ownership of Rappi or merchant content.
