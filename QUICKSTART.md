# Quick start

This page is the short command guide. The main [`README.md`](README.md) explains the files, method,
and output structure.

## 1. Install

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## 2. Check the full plan without using the network

```bash
python -m rappi_co.study --all-countries --dry-run
```

Expected plan: four countries, two locations per country, and 242 requests.

## 3. Test one query at both locations

```bash
python -m rappi_co.study --country ar --terms cigarrillos --collect-only
```

Review the two raw output folders before starting the complete run.

## 4. Run one complete country

```bash
python -m rappi_co.study --country ar
```

Valid country codes are:

- `ar` for Argentina
- `co` for Colombia
- `pe` for Peru
- `mx` for Mexico

The final workbook is written to:

```text
data/<country>/processed/combined/tobacco_master_<run_id>.xlsx
```

## 5. Rebuild from an existing complete raw run

```bash
python -m rappi_co.study --country ar --skip-collect
```

The historical raw files for the published workbooks are not included here. This command works with
raw files created locally by the same pipeline.

## 6. Run the tests

```bash
python -m pytest tests -q
```

## Main configuration files

```text
config/study/terms.yml                 shared search terms
config/study/brand_terms_ar.yml        Argentina brands
config/study/brand_terms_co.yml        Colombia brands
config/study/brand_terms_pe.yml        Peru brands
config/study/brand_terms_mx.yml        Mexico brands
config/study/zones_<country>.yml       delivery locations
config/study/countries.yml             country and currency settings
```

Stop if Rappi returns a CAPTCHA or an access challenge. The workflow does not bypass access controls.
