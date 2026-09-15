# Final country product workbooks

This directory contains one final workbook for Argentina, Colombia, Peru and
Mexico. Each workbook has exactly five sheets in this order: `Technical
specifications`, `Tobacco products`, `SSBs`, `Water`, and `Alcohol`.

The four files contain 68,398 study observations. Every row in the `SSBs`
worksheets belongs to an unconfirmed screening cohort; all quantitative sugar
fields are blank, and blank means unknown rather than zero. Alcohol fields are
shown there as cross-category checks. Product-detail pages are not included.
The beverage source did not provide a validated row-level brand field, so
beverage brands were not inferred from titles. `Technical specifications` is a
plain-language workbook guide followed by a structured data dictionary. Each
category sheet starts with category measures and selected source context.
Additional raw source fields, measurement evidence and provenance are grouped
in hidden columns to the right; the guide marks every field Shown or Hidden.

Availability is a normalized listing status at collection. Raw beverage stock
values are retained in hidden columns but are not verified inventory counts.

Rebuild offline into a new directory:

```sh
python -m rappi_co.export.country_product_workbooks --out data/country_products_rebuild
```

`manifest.json` records the exact inputs, columns, output hashes, and counts.
