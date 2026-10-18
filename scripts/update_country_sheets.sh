#!/usr/bin/env bash
# Create a new, verified release for four countries. Never overwrites datasets/.
set -euo pipefail

release_date="${1:-$(date +%Y%m%d)}"
destination="data/updates/${release_date}"

python -m rappi_co.release_update --out "$destination" --dry-run
python -m rappi_co.release_update --out "$destination" --collect
printf 'Verified updated workbooks: %s/country_products\n' "$destination"
