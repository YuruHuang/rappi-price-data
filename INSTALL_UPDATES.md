# Install the country team updates

This update adds `python -m rappi_co.run` and flexible location and query files.
It contains changed code, tests, examples, and documentation, with paths relative
to the repository root. It does not contain collected data or credentials.

On a fresh checkout, place `Rappi_country_team_code_updates.zip` beside the
`rappi-price-data` folder, then run from the repository root:

```zsh
unzip -o ../Rappi_country_team_code_updates.zip -d .
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q
python -m rappi_co.run --country co \
  --locations-file config/examples/locations_co.csv \
  --scope both \
  --out data/updates/co_MY_RUN --dry-run
```

If the checkout contains local edits, review and preserve them before replacing
files. `git diff --stat` and `git diff` show the applied changes in a Git checkout.
After review, the owner can commit and publish them through the normal workflow.

This command keeps the original published country terms, including brands and
local wording. Custom terms files are optional. The beverage default matches
version 1; the later expanded list is saved separately in `config/archive/beverages_v2.yml`.

Replace `--dry-run` with `--collect` only when the plan is ready for a live run.
See `docs/country_team_guide.md` for the full walkthrough.
The location input needs checked latitude and longitude; street
addresses are not automatically geocoded.
