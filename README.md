# Rappi price data

Rappi product listings from two delivery locations in each of Argentina,
Colombia, Peru, and Mexico. The release covers tobacco and nicotine products,
water, alcohol, and beverage candidates for review as sugar-sweetened
beverages (SSBs).

## 📦 Data

[`datasets/country_products/`](datasets/country_products/) contains one
analysis-ready workbook per country. Each workbook has five sheets:
`Technical specifications`, `Tobacco products`, `SSBs`, `Water`, and `Alcohol`.

| Country | Workbook | Rows | Currency |
| --- | --- | ---: | --- |
| Argentina | [argentina.xlsx](datasets/country_products/argentina.xlsx) | 17,556 | ARS |
| Colombia | [colombia.xlsx](datasets/country_products/colombia.xlsx) | 18,021 | COP |
| Peru | [peru.xlsx](datasets/country_products/peru.xlsx) | 18,322 | PEN |
| Mexico | [mexico.xlsx](datasets/country_products/mexico.xlsx) | 14,499 | MXN |
| **Total** |  | **68,398** |  |

Each row is a product listing from one store at one delivery location and one
collection time. Products can appear in more than one row. Field definitions,
units, and collection dates are in the `Technical specifications` sheet.

### What the data do and do not show

- Tobacco was collected on 16 August 2026; beverages on 10 September 2026.
  Do not compare the two waves as if they were collected on the same day.
- The SSB sheet is a screening set, not a confirmed measure of sugar content.
  Sugar is unconfirmed for every row; blank sugar fields mean unknown.
- Results describe the sampled Rappi listings. They do not measure the full
  catalogue, national availability, sales, consumption, or market share.
- Product-detail pages and verified stock counts are not part of this release.

### How the collection was designed

The same general terms are used in every country. Country terms cover local
product language, and brand terms act as additional discovery seeds. Two
delivery locations per country capture some variation in store coverage without
presenting the results as nationally representative. Listings with unresolved
sugar status stay in review rather than being labelled as SSBs.

## 🚬 Tobacco terms

The tobacco search plan covers four product families: nicotine pouches,
electronic cigarettes, heated tobacco, and cigarettes. The shared Spanish
queries are `bolsas de nicotina`, `cigarrillos electronicos`, `vapeador`,
`vapeadores`, `productos de tabaco calentado`, and `cigarrillos`.

Each country also has a reviewed set of brand-qualified searches. These are
discovery seeds, not a brand ranking or evidence of national availability. The
archived August 2026 protocol used 27 queries in Argentina, 32 in Colombia, 30
in Peru, and 32 in Mexico, at both study locations.

The shared terms are in [`config/study/terms.yml`](config/study/terms.yml).
Country brand lists are in
[`config/study/`](config/study/), with the exact queries and collection notes
for [Argentina](docs/countries/argentina.md),
[Colombia](docs/countries/colombia.md), [Peru](docs/countries/peru.md), and
[Mexico](docs/countries/mexico.md). A new tobacco term should be tested as a
separate, dated protocol update; a missing search result does not show that a
product was absent from the country.

## 🧭 Beverage terms

The archived beverage release used version 1 of the search list. Version 2 is
used for the next collection. It adds these tested country-specific terms:

- Argentina: `bebida lactea`, `limonada`, `cafe frio`, `vermut`, `aperitivo`
- Colombia: `bebida lactea`, `bebida de malta`, `limonada`, `cafe frio`, `hard seltzer`
- Peru: `bebida lactea`, `limonada`, `cafe frio`, `hard seltzer`, `bebida preparada`
- Mexico: `bebida lactea`, `horchata`, `cafe frio`, `pulque`, `hard seltzer`

The pilot ran 40 searches across the eight study locations. All completed, but
some results were capped and broad terms produced many records for review.
These are search terms only; they do not define a product category or confirm
that a product is an SSB.

The current list is [`config/beverages.yml`](config/beverages.yml). The exact
version-1 file used for the archived release is
[`config/archive/beverages_v1.yml`](config/archive/beverages_v1.yml).

### Add a beverage term

1. Define the country and beverage family the term should find.
2. Test it at both configured locations in a dated pilot directory:

   ```sh
   python -m rappi_co.beverages --country mx --terms "horchata" \
     --data-root data/pilots/beverage_term_check_YYYYMMDD
   ```

3. Review `beverage_query_yield_*.csv`, `beverage_coverage_*.csv`, and the
   review workbook. Check duplicates, capped store groups, and the returned
   product families. A non-empty result is not enough.
4. Add a general term to `categories`, a country term to `regional_terms`, or
   a named product search to `brand_queries`. Increment `version` and update
   the changelog and study protocol.
5. Run the full plan with `--dry-run` before collecting. A changed search list
   is a new protocol; do not add its records to an archived release.

## 🗂️ Repository map

```text
datasets/
├── country_products/   analysis-ready country workbooks
├── integrated/         full release, review records, and comparison records
├── beverages/          archived beverage release
└── *.xlsx              archived tobacco release
docs/
├── study_protocol.md   study design and classification rules
└── countries/          country collection notes
config/                 search terms, locations, and settings
rappi_co/               collection, classification, validation, and export code
tests/                  automated checks
```

The integrated and country workbooks contain the same observations in different
formats. Do not append them together.

## ♻️ Reproduce the published release

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m rappi_co.export.country_product_workbooks \
  --out data/country_products_rebuild
python -m pytest -q
```

Use a new output directory. The exporter checks source hashes, row counts,
identifiers, formulas, and written values.

## 🔄 Collect a new release

The files in `datasets/` are archived. New collection output belongs in a new,
dated directory.

```sh
python -m rappi_co.beverages --all-countries --dry-run
python -m rappi_co.release_update --out data/updates/YYYYMMDD --dry-run
python -m rappi_co.release_update --out data/updates/YYYYMMDD --collect
```

The update writes new country workbooks under
`data/updates/YYYYMMDD/country_products/`. It stops on a CAPTCHA or access
challenge. Resume an interrupted run with the same output directory and
`--resume`.

## 📌 Citation, contributions, and license

Use [`CITATION.cff`](CITATION.cff) to cite the repository and release manifest.
See [`CONTRIBUTING.md`](CONTRIBUTING.md) for corrections or reproducible
updates, and [`CHANGELOG.md`](CHANGELOG.md) for release changes. The software
license is in [`LICENSE`](LICENSE); it does not claim ownership of Rappi or
merchant content.
