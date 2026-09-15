# Beverage source workbooks

These four workbooks are the reviewed beverage source release used to build the
final country files. They cover water, sugar-sweetened beverage candidates, and
alcohol at the same eight delivery locations as the tobacco study.

Collection finished on 10 September 2026 UTC, beginning on 9 September in
America/Chicago. The pipeline made 356 searches and received 84,849 raw
product-store-location observations before classification.

| Country | Workbook | Raw observations | Water | SSB candidates | Alcohol |
| --- | --- | ---: | ---: | ---: | ---: |
| Argentina | [argentina.xlsx](argentina.xlsx) | 24,281 | 1,464 | 6,073 | 7,694 |
| Colombia | [colombia.xlsx](colombia.xlsx) | 17,980 | 1,045 | 6,116 | 6,317 |
| Peru | [peru.xlsx](peru.xlsx) | 22,949 | 806 | 4,673 | 9,469 |
| Mexico | [mexico.xlsx](mexico.xlsx) | 19,639 | 1,741 | 6,367 | 5,794 |

Open `summary` first. The `items` worksheet contains classified water, confirmed
SSBs, and alcohol. The `ssb_candidates` worksheet contains the wider candidate
set, including recognizable drink families whose sweetening remains unknown.
Candidate rows can also appear in `items` or `review`, so worksheet totals must
not be added together.

The workbooks keep volume per container, pack count, total sale volume, sugar,
and alcohol-by-volume fields with their supporting evidence. Unsupported or
conflicting values remain blank. A no-sugar claim is not recorded as a measured
zero, and a per-liter price is calculated only when total volume is supported.
Prices remain in ARS, COP, PEN, or MXN.

No supported quantitative sugar concentrations were found in the archived
search responses. The candidate set is therefore suitable for product review,
not for estimating sugar content. Product-detail pages are outside this
release.

The `coverage`, `query_yield`, `stores`, `locations`, and `data_dictionary`
worksheets describe the sample and fields. [`coverage_audit.json`](coverage_audit.json)
records observed result counts by query group. [`manifest.json`](manifest.json)
and the four provenance files record counts, query plans, checksums, and code
hashes.

For the final five-sheet delivery, use
[`datasets/country_products/`](../country_products/). The [study protocol](../../docs/study_protocol.md)
explains the shared sampling and classification rules.
