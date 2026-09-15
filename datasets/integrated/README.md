# Integrated source-preserving workbooks

This release combines the original tobacco and beverage observations without
discarding comparison, unresolved, or excluded beverage records. Use it when
those audit populations are needed. For the simpler five-sheet delivery, use
[`datasets/country_products/`](../country_products/).

| Country | Workbook | Tobacco | Water | SSB candidates | Alcohol | All retained records |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Argentina | [argentina.xlsx](argentina.xlsx) | 2,325 | 1,464 | 6,073 | 7,694 | 26,606 |
| Colombia | [colombia.xlsx](colombia.xlsx) | 4,543 | 1,045 | 6,116 | 6,317 | 22,523 |
| Peru | [peru.xlsx](peru.xlsx) | 3,374 | 806 | 4,673 | 9,469 | 26,323 |
| Mexico | [mexico.xlsx](mexico.xlsx) | 597 | 1,741 | 6,367 | 5,794 | 20,236 |
| **Total** | [all_countries.xlsx](all_countries.xlsx) | **10,839** | **5,056** | **23,229** | **29,274** | **95,688** |

The four target groups contain 68,398 observations. Another 27,290 records are
comparisons, unresolved beverage records, or exclusions. Counts refer to
store-location-product observations and can include the same product from more
than one store or delivery point.

Tobacco was collected on 16 August 2026 and beverages on 10 September 2026.
The integration preserves both collection dates and does not make the two waves
contemporaneous. Prices remain in local currency.

## Workbook layout

Each country workbook has a guide and seven disjoint data worksheets:

| Worksheet | Contents |
| --- | --- |
| `Tobacco` | Included cigarettes, electronic cigarettes, heated tobacco, and nicotine pouches. |
| `Water` | Plain still or sparkling drinking water. |
| `SSB_candidates` | The published candidate cohort; sweetening may remain unknown. |
| `Alcohol` | Alcoholic beverages; ABV appears only when supported by source evidence. |
| `Comparison` | Relevant non-SSB comparisons, including diet and no-sugar variants. |
| `Review` | Unresolved beverage observations. |
| `Excluded` | Search results excluded from the target groups but retained for audit. |

The combined workbook has one worksheet per country and a `reporting_group`
column that reproduces the same partition. Do not append the combined workbook
to the country files because it contains the same observations.

The files also include coverage, location, dictionary, and source information.
Primary analysis columns appear first. Detailed source and evidence fields are
kept to the right and hidden by default. They can be unhidden in Excel. No
worksheets are hidden.

Blank quantitative fields mean missing or unresolved, not zero. The source
release contains no supported sugar concentrations. Beverage volume fields are
kept separate from tobacco package and strength fields, and identifiers remain
text so leading zeros and long values are preserved.

[`manifest.json`](manifest.json) records input and output checksums, collection
dates, columns, and partition counts. To rebuild into a new directory:

```sh
python -m rappi_co.export.integrated_deliverable \
  --out data/integrated_rebuild
```

The rebuild requires the archived beverage audit files referenced by the
provenance records. The published workbooks can be analyzed without those local
archives. See the [study protocol](../../docs/study_protocol.md) for the sample,
classification rules, and limitations.
