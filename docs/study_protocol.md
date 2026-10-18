# Study protocol

## Purpose and unit of observation

This study records tobacco and nicotine products, water, sugar-sweetened
beverage candidates, and alcohol visible through Rappi at selected delivery
locations in Argentina, Colombia, Peru, and Mexico.

One row is one product offered by one store at one delivery location and
collection time. It is not a purchase or a nationally unique product. A product
can appear more than once when different stores or locations offered it.

The data describe the sampled online assortment. They do not measure national
availability, sales, consumption, or market share.

## Geographic and temporal coverage

Two public landmarks in one city were used as reproducible delivery points in
each country.

| Country | City | Delivery points | Currency | Tobacco searches | Beverage searches |
| --- | --- | --- | --- | ---: | ---: |
| Argentina | Buenos Aires | Galerías Pacífico; Alto Palermo | ARS | 54 | 90 |
| Colombia | Bogotá | Plaza Bolívar; Andino | COP | 64 | 88 |
| Peru | Lima | Larcomar; MegaPlaza | PEN | 60 | 88 |
| Mexico | Mexico City | Bellas Artes; Perisur | MXN | 64 | 90 |

Tobacco was collected on 16 August 2026. Beverages were collected on
10 September 2026 UTC, with collection beginning the previous evening in
America/Chicago. The workbook records retain these dates. Prices from the two
waves should not be treated as contemporaneous.

Coordinates, addresses, currencies, service hosts, and country settings are in
[`config/study/`](../config/study/). Country source notes are available for
[Argentina](countries/argentina.md), [Colombia](countries/colombia.md),
[Peru](countries/peru.md), and [Mexico](countries/mexico.md).

## Product discovery

The search plan uses several complementary layers:

1. Shared generic category terms provide a consistent base across countries.
2. Regional Spanish terms cover common local wording and product families.
3. Country-specific brand queries include familiar local-market names and
   large international brands.
4. Comparison terms retain diet, no-sugar, alcohol-free, and adjacent products
   needed to distinguish the target categories.

The tobacco terms and reviewed country brand lists are under
[`config/study/`](../config/study/). Beverage terms and brand queries are in
[`config/beverages.yml`](../config/beverages.yml). Brand labels are search aids.
“Local-market” does not claim local ownership or manufacture, and an
international brand can also be produced locally.

The beverage source did not provide a validated row-level brand field. The
final beverage sheets therefore do not infer brands from product titles; the
brand examples in Technical specifications document search coverage only.

The keywords are designed for broad, reproducible discovery, but no finite list
can guarantee a complete platform catalog. Search results depend on the address,
time, store participation, ranking, and platform response. Missing results do
not establish that a product or brand was unavailable elsewhere in the country.

The archived September 2026 beverage release used configuration version 1.
Version 2 is a prospective protocol: after an October 2026 pilot at both
configured locations in each country, it adds five country-specific discovery
terms per country. The pilot confirmed that each term returned listings and
could be processed without an access or export error. It did not establish
complete catalogue coverage, product prevalence, or SSB status. The terms are
therefore used only for discovery in future collections. The procedure for
testing and adopting further terms is documented in the repository README.

## Collection and record handling

The collector sends the planned queries for both delivery points and archives
the raw response for later inspection. It records the query, country, location,
store, product identifiers, price, currency, timestamp, and returned product
attributes.

Within one location, repeated discoveries of the same `(store_id, product_id)`
are combined while retaining the search terms that found the item. The final
tobacco observation key is `(country_code, zone_slug, store_id, product_id)`.
Integrated records also retain their source dataset and release so observations
from the two collection waves cannot be confused.

HTTP access failures and unexpected HTML responses stop collection. The
pipeline uses bounded retries for temporary server errors and does not bypass
CAPTCHAs or access controls. Credentials and browser state are excluded from
the repository.

## Classification

Classification uses deterministic rules. The final country workbooks retain
the resulting category and relevant product attributes; internal diagnostic
fields used to review the rules are omitted from those workbooks.

| Group | Working definition |
| --- | --- |
| Tobacco products | Cigarettes, eligible electronic-cigarette products, heated-tobacco consumables, and nicotine pouches. Standalone devices, accessories, unrelated keyword matches, and tobacco-containing oral products are excluded from the final group. |
| Water | Plain drinking water, still or sparkling. Flavored, functional, coconut, and prepared fruit waters require separate classification. |
| SSBs | A screening cohort of recognizable nonalcoholic beverage families. Sweetening is unconfirmed for every row in this release; a family or brand match does not prove added sugar. |
| Alcohol | Products whose alcoholic identity is supported by the title or returned attributes. Alcohol-free variants and ambiguous cocktail products remain outside the final target group in source-preserving comparison or review records. |

The original tobacco rules are described in
[`docs/methodology.md`](methodology.md). Broad search results that do not meet a
target definition remain available in the source-preserving workbooks as
comparison, review, or excluded observations.

## Quantitative fields

Measurements are recorded only when the listing supplies a usable basis.

- Beverage volume per container, pack count, and total sale volume are separate
  fields. Price per liter is calculated only from a supported total volume.
- Sugar amount, unit, nutrient name, and reporting basis are kept separately.
  A serving value is not converted to grams per 100 mL without an explicit
  serving volume. “No added sugar” is not treated as zero total sugar.
- Alcohol by volume is retained only when an explicit percentage or structured
  attribute supports it. An ambiguous percentage is left unresolved.
- Tobacco fields retain their product-specific meanings, including package
  count, unit price, nicotine strength, liquid volume, and puff count where
  applicable.

Blank numeric cells mean missing or unresolved, not zero. The archived beverage
search responses supplied no supported quantitative sugar concentrations, so
the final `SSBs` sheets should not be used to estimate sugar content.

Alcohol indicators and ABV are shown on the SSB sheets as cross-category checks
for candidates that may require review. Availability is a normalized listing
status at collection. Raw beverage stock values are retained in hidden columns,
but they are not verified inventory counts.

Product-detail pages are outside the final dataset. Product names and attributes
come from the collected listing responses; a later product page is not joined
to an earlier store-price observation.

## Outputs and quality checks

The final delivery contains one workbook per country in
[`datasets/country_products/`](../datasets/country_products/). Each has
`Technical specifications`, `Tobacco products`, `SSBs`, `Water`, and `Alcohol`
in that order. Category-specific fields appear first, and supporting provenance
and additional raw source fields remain available in a hidden block to the
right. The Technical specifications sheet identifies each field as shown or
hidden.

The exporter checks source hashes, observation keys, country totals, category
partitions, currencies, numeric types, and workbook values. It also checks that
the final files contain no formulas, macros, external workbook links, or hidden
worksheets. Manifests beside the releases record file hashes, counts, and exact
inputs.

The published values remain source observations. Validation can detect a
processing or export inconsistency, but it cannot independently verify every
merchant description, price, package claim, or inventory status.
