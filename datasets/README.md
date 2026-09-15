# Tobacco source workbooks

For tobacco, water, SSB candidates, and alcohol together, use the
[integrated release](integrated/README.md): four country workbooks and one
combined workbook. The original files below are preserved source snapshots.

Water, SSB candidates, and alcohol have a separate [beverage first pass](beverages/README.md).
The notes and counts below describe the original tobacco release.

The four workbooks are the country data files currently included in this repository. They
were built from Rappi responses collected on 16 August 2026 at two delivery points per country and
regenerated with the final classification and workbook formatting code on 20 August 2026.

| Country | Items | Cigarettes | Electronic cigarettes | Heated tobacco | Nicotine pouches |
|---|---:|---:|---:|---:|---:|
| Argentina | 2,325 | 2,039 | 97 | 0 | 189 |
| Colombia | 4,543 | 1,239 | 2,783 | 208 | 313 |
| Peru | 3,374 | 676 | 2,537 | 0 | 161 |
| Mexico | 597 | 266 | 5 | 102 | 224 |
| **Total** | **10,839** | **4,220** | **5,422** | **310** | **887** |

Counts are store-location-product observations, not unique national products. The zero heated-tobacco
counts in Argentina and Peru mean that no qualifying observations surfaced at the sampled points and
time; they do not establish national absence. Mexico's five electronic-cigarette observations came
from one reviewed retailer at one sampled location and should not be interpreted as national supply.

Known source-price cautions include one Peruvian cigarette listing at PEN 2,670, eight Peruvian pouch
promotions at PEN 0.75, and two Mexican `Winston Red 20's` listings at MXN 1.75. These values match the
source response and were not silently replaced.

The workbooks contain no formulas, external links, macros, hidden sheets, or raw authentication and
session data. SHA-256 checksums are recorded in [`manifest.json`](manifest.json).

The repository software license does not assert ownership of source-platform or merchant content.
Use and redistribute the observations in accordance with applicable institutional and source terms.
