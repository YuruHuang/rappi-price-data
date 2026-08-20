# Quick start

## Open the published data

Download one of the four files under [`datasets/`](datasets/):

- `argentina.xlsx`
- `colombia.xlsx`
- `peru.xlsx`
- `mexico.xlsx`

Start with the `summary` sheet. The main observations are in `items`, and every column is defined in
`data_dictionary`.

## Inspect the study plan

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m rappi_co.study --all-countries --dry-run
```

The dry run prints all eight locations, the exact ordered queries, and the request total without
contacting Rappi.

## Run one country

```bash
python -m rappi_co.study --country pe
```

This collects both configured Peruvian locations, writes a raw completion manifest for each one,
classifies the products offline, and creates the combined CSV and Excel outputs under `data/pe/`.

To rebuild from your own previously completed raw archive:

```bash
python -m rappi_co.study --country pe --skip-collect
```

The archived raw inputs used for the four published workbooks are not included in this repository.

## Verify the code

```bash
python -m pytest tests -q
```

Read [`docs/methodology.md`](docs/methodology.md) before collecting or interpreting results. The
workflow stops on CAPTCHAs or access challenges and does not attempt to bypass them.
