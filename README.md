# Rappi price data

This repository contains Rappi product-listing data and the code used to collect it. The study covers tobacco and nicotine products, water, alcohol, and beverage candidates for review as sugar-sweetened beverages (SSBs) in Argentina, Colombia, Peru, and Mexico.

## For country teams

Use this sequence before any new collection.

### 1. Confirm the delivery points

The study uses two fixed delivery points in each city. They are part of the protocol: do not substitute a nearby address during a run.

| Country | City | Delivery points | Details |
| --- | --- | --- | --- |
| Argentina | Buenos Aires | Galerías Pacífico; Alto Palermo | [country note](docs/countries/argentina.md) |
| Colombia | Bogotá | Plaza Bolívar; Andino | [country note](docs/countries/colombia.md) |
| Peru | Lima | Larcomar; MegaPlaza | [country note](docs/countries/peru.md) |
| Mexico | Mexico City | Bellas Artes; Perisur | [country note](docs/countries/mexico.md) |

Each country note gives the address, district, coordinates, and tobacco collection context. The source files are [`config/study/zones_ar.yml`](config/study/zones_ar.yml), [`zones_co.yml`](config/study/zones_co.yml), [`zones_pe.yml`](config/study/zones_pe.yml), and [`zones_mx.yml`](config/study/zones_mx.yml).

If a point no longer receives Rappi delivery, record the result. Propose a replacement with its full address, coordinates, district, and reason for the change. Update the zone file and country note before using the replacement.

### 2. Review the terms

Run the full dry run first. It makes no network requests and prints the two locations and every tobacco and beverage query.

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

The full update command collects all four countries and writes a new package.

```sh
python -m rappi_co.release_update --out data/updates/YYYYMMDD --collect
```

Do not write into `datasets/`. If the run stops, use the same output directory:

```sh
python -m rappi_co.release_update --out data/updates/YYYYMMDD --collect --resume
```

Before sharing the result, check `data/updates/YYYYMMDD/manifest.json`, the four workbooks in `country_products/`, and the recorded source manifests. The update command checks source hashes, row identities, category partitions, and workbook contents; it stops when Rappi returns an access challenge.

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

The archived beverage release used version 1 of [`config/beverages.yml`](config/beverages.yml). Version 2 is the plan for the next collection. It adds:

- Argentina: `bebida lactea`, `limonada`, `cafe frio`, `vermut`, `aperitivo`
- Colombia: `bebida lactea`, `bebida de malta`, `limonada`, `cafe frio`, `hard seltzer`
- Peru: `bebida lactea`, `limonada`, `cafe frio`, `hard seltzer`, `bebida preparada`
- Mexico: `bebida lactea`, `horchata`, `cafe frio`, `pulque`, `hard seltzer`

The 40-search pilot completed in October 2026. It confirmed that the new terms returned listings, not that they provide complete coverage or identify SSBs. The exact version-1 file used for the published beverage release is retained at [`config/archive/beverages_v1.yml`](config/archive/beverages_v1.yml).

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

## Reproduce the published workbooks

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
