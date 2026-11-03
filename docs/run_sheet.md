# Rappi run sheet

Country teams · macOS Terminal

Choose your delivery points and search terms, then collect a new Excel workbook. These examples use Colombia. For another country, use its code in `--country`, the term-file paths, and your output folder name. Keep `rappi_co` as written.

**Country codes**  `ar` Argentina · `co` Colombia · `pe` Peru · `mx` Mexico

## 1 Get set up

You need Git, Python 3.12, and access to the repository. In Terminal, go to the folder where you want to keep the project, then run:

```zsh
git clone https://github.com/YuruHuang/rappi-price-data.git
cd rappi-price-data
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Already cloned? Enter that project folder, check `git status`, preserve any local edits, then run `git pull --ff-only`. Activate the existing environment with `source .venv/bin/activate`. All commands below run from the project folder. Scrapy is not needed.

## 2 Add your delivery points

```zsh
mkdir -p inputs
cp -n config/examples/locations_multi_country.csv inputs/locations.csv
open -e inputs/locations.csv
```

The template has example points for all four countries. Replace them with your checked locations. Keep the headers and country tags; add or delete whole rows, then save. You can use as many valid points as you need.

| Field | What to enter |
| --- | --- |
| address | The full written address. |
| lat and lng | Checked coordinates for that address. These determine where Rappi searches. |
| slug | Your own short, unique ID, such as centro-01. Keep it stable across runs. |
| country_code | ar, co, pe, or mx. Required on every row when using a multi-country file. |

The code does not look up coordinates or verify the address. Keep city and district if useful. CSV, TSV, XLSX, JSON, and YAML location files work; point the command to your actual file.

## 3 Keep or edit the search terms

```zsh
cp -n config/examples/terms/co_tobacco.csv inputs/co_tobacco.csv
cp -n config/examples/terms/co_beverages.csv inputs/co_beverages.csv
open -e inputs/co_tobacco.csv inputs/co_beverages.csv
```

These copies contain the **full original country lists**, including local wording and brands. Leave them unchanged to keep those searches. To change them, keep the `term` header and add or delete rows, then save.

A supplied file becomes the whole query list for that topic. Keep every original term you still want. `cp -n` preserves an existing copy, including your previous edits.

<!-- pagebreak -->

# Run and open the results

## 4 Preview the plan

```zsh
python -m rappi_co.run --country co --scope both \
  --locations-file inputs/locations.csv \
  --tobacco-terms-file inputs/co_tobacco.csv \
  --beverage-terms-file inputs/co_beverages.csv \
  --out data/updates/co_run_01 \
  --dry-run
```

Check the locations, full query lists, and `planned_search_requests`. The unchanged Colombia inputs plan 152 searches. The preview makes no requests to Rappi.

**To collect, run the same command with `--collect` instead of `--dry-run`.** Use a fresh output name for each new collection; the program creates that folder. Keep the inputs unchanged while it runs.

## 5 Open the workbook

After a successful run:

```zsh
open data/updates/co_run_01/country_products/colombia.xlsx
```

| Scope | Workbook | Tabs |
| --- | --- | --- |
| both | colombia.xlsx | Technical specifications, Tobacco products, SSBs, Water, Alcohol |
| beverages | co_beverages.xlsx | SSBs, Water, Alcohol |
| tobacco | co_tobacco.xlsx | Technical specifications, Tobacco products |

Other combined filenames are argentina.xlsx, peru.xlsx, and mexico.xlsx. Single-topic filenames use the country code.

## Collect beverages or tobacco

```zsh
python -m rappi_co.run --country co --scope beverages \
  --locations-file inputs/locations.csv \
  --terms-file inputs/co_beverages.csv \
  --out data/updates/co_beverages_01 --dry-run
```

For tobacco, use `--scope tobacco`, `--terms-file inputs/co_tobacco.csv`, and a fresh output name. Preview, then change `--dry-run` to `--collect`. Omit term options to use the built-in original lists.

## Collect several countries

Use the same locations file, with a `country_code` on every row and at least one matching point per selected country. The command selects each country's rows. Preview Colombia and Mexico:

```zsh
python -m rappi_co.release_update --country co --country mx \
  --locations-file inputs/locations.csv \
  --out data/updates/co_mx_run_01 --dry-run
```

This uses each country's original terms. Review, then replace `--dry-run` with `--collect`; each country gets a five-tab workbook. For all four countries, omit the country options. For edited term files or one topic, use `rappi_co.run` once per country instead.

Keep the whole run folder. Searches pause one to three seconds and stop on an access challenge. SSBs includes candidates whose sweetening is unconfirmed.

[Full country team guide](country_team_guide.md)
