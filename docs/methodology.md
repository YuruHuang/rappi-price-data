# Rappi tobacco product data collection in four countries

## Purpose

This collection workflow adapts the Colombia search collector to Argentina, Colombia,
Peru, and Mexico. It
samples two public delivery locations in one major Rappi city per country. It does not claim national
coverage or market share.

The historical two-location Colombia workflow remains in the repository for compatibility. Its files
use `config/zones_co.yml`, `config/relevant_sections_co.yml`, and the original commands. The four
country collection uses the separate `config/study/` directory and always requires `--country`.

## Collection scope

| Code | Country | Sampled city | Currency | Locations | Default queries | Requests |
|---|---|---|---|---:|---:|---:|
| `ar` | Argentina | Buenos Aires | ARS | 2 | 27 | 54 |
| `co` | Colombia | Bogotá | COP | 2 | 32 | 64 |
| `pe` | Peru | Lima | PEN | 2 | 30 | 60 |
| `mx` | Mexico | Mexico City | MXN | 2 | 32 | 64 |

The request count is locations multiplied by queries. A complete default pass is 242 search
requests, paced with a random one-to-three-second delay unless changed on the command line. A full
country protocol means both configured locations and the exact ordered default query list. Any
location subset or different query sequence is a partial diagnostic run; its derived files are
isolated from the normal country outputs and must not be reported as complete country results.

## What “international” and “local-market” mean

The brand lists are search seeds, not rankings.

- `international` is used for established brands distributed across several markets.
- `local_market` means the brand has particular visibility or relevance in that country's Rappi
  market. It does not mean the brand is locally owned or manufactured.

The lists contain no more than ten brands in a category. They are deliberately shorter when current
evidence supports fewer brands. National market-share data were not used to fill gaps.

## How the locations were selected

Each location is a public cultural or commercial landmark. This avoids using a person's home address
and makes the point easier for another researcher to reproduce.

The selection process was:

1. Choose two well-known locations in different parts of the sampled city.
2. Verify the street address using a venue, tourism authority, or government source.
3. Record a WGS84 latitude and longitude from the venue's map marker or an OpenStreetMap-derived
   record.
4. Apply a coarse city bounding-box check when loading the configuration.
5. Before a full run, send one ordinary search request at each point to confirm that Rappi returns
   stores for the pin.

Mall-centroid and landmark coordinates are sampling coordinates. They are not store coordinates, and
two points cannot represent an entire city or country.

Country-specific address evidence is recorded in:

- [Argentina](countries/argentina.md)
- [Colombia](countries/colombia.md)
- [Peru](countries/peru.md)
- [Mexico](countries/mexico.md)

## How the queries were built

### Fixed generic terms

The generic scope is intentionally narrow and is shared by all four countries:

| Category | Query |
|---|---|
| Nicotine pouches | `bolsas de nicotina` |
| Electronic cigarettes | `cigarrillos electronicos` |
| Electronic cigarettes | `vapeador` |
| Electronic cigarettes | `vapeadores` |
| Heated tobacco | `productos de tabaco calentado` |
| Cigarettes | `cigarrillos` |

These are the six generic values in the default protocol and are stored in
`config/study/terms.yml`. Broader terms such as bare `nicotina`, `tabaco`, or `pod` were not added
because they substantially increase unrelated results. A command-line `--terms` override is for
smoke tests or explicitly labeled exploratory runs.

### Brand-qualified terms

Brand research used current indexed Rappi country pages first, then manufacturer or government
sources to understand whether a name was an active portfolio brand or a locally relevant line. Every
brand is qualified with its category. Examples are `marlboro cigarrillos`, `zyn bolsas de nicotina`,
and `geek bar vapeador`. A bare ambiguous name such as `camel`, `master`, or `kent` is never sent.

Generic queries run first. Brand-qualified queries then improve recall for products that Rappi does
not return under a generic term. Search output records the first `source_term` that surfaced each
de-duplicated product.

The source pages were checked on 2026-08-16. Rappi availability remains address- and time-specific,
so a configured brand can return no results in a later run.

## How collection works

`rappi_co.collect.search` sends one POST per query to the country service host in
`config/study/countries.yml`, with the configured latitude and longitude. The public website and
service hosts are stored separately because Rappi does not use one search host across all four
countries. The collector then:

1. walks every returned store group and product;
2. maps the source fields into a stable row schema;
3. de-duplicates by `(store_id, product_id)` within the location while retaining every query that
   surfaced the product;
4. writes products and store coverage as CSV;
5. archives every raw JSON response as gzip so fields can be re-parsed without another request;
6. writes a completion manifest with the exact ordered queries, endpoint, coordinates, paths, and
   row counts.

Collection files are isolated by country and location:

```text
data/<country>/raw/<zone>/search_items_<timestamp>.csv
data/<country>/raw/<zone>/search_stores_<timestamp>.csv
data/<country>/raw/<zone>/search_raw_<timestamp>/*.json.gz
data/<country>/raw/<zone>/search_manifest_<timestamp>.json
```

For non-Colombia rows, `price_cop` is left blank. `price_local` holds the returned amount and
`currency` states whether it is ARS, COP, PEN, or MXN. This prevents an Argentine, Peruvian, or
Mexican price from being mislabeled as Colombian pesos. A Colombia-specific display-unit parser is
not reused for non-COP decimal prices; trusted unit prices are derived during export from a credible
pack count.

## Access challenges and rate limits

The workflow uses the ordinary search interface and conservative pacing. It does not attempt to
solve, bypass, or conceal a CAPTCHA or other access control.

- HTTP 401 or 403 stops immediately with a clear error.
- A 200 response containing HTML rather than JSON is treated as a possible browser challenge and is
  not parsed as data.
- HTTP 429 and temporary server errors use bounded retry and backoff.
- Raw credentials and browser state remain under ignored `data/` paths and must not be committed.

If a challenge appears, stop the run. Retry later or use a session that the researcher has manually
and legitimately authorized. Do not add stealth plugins, CAPTCHA services, or automated challenge
solving.

## Classification

Classification is offline and deterministic. The shared Spanish tobacco lexicon handles generic
product language. At runtime, the selected country's reviewed brands extend that lexicon.

Brands marked `distinctive` can support a tobacco classification by themselves. Ambiguous names such
as `Camel`, `Master`, `Kent`, or `Montana` are `context_required`: the product also needs a tobacco
aisle, a health-warning signal, or a word such as `cigarrillos`, `cajetilla`, or `nicotina`. This is
the main protection against false positives such as Camel clothing or Master household products.

The classifier writes its rule, rationale, confidence, product type, and review flags. The final
export then keeps only the four agreed families: `nicotine_pouch`; the vape family (`vape`,
`vape_disposable`, `vape_pod`, `vape_liquid`); `heated_tobacco`; and `cigarette`. Cigars, rolling
tobacco, pipe tobacco, shisha, cessation products, paraphernalia, standalone heated devices
(`heated_device`), and the observed tobacco-containing oral products (`smokeless_tobacco`) remain
available in the run-specific offline classification file for review but are not included in the
workbook. There is no model or external API in this stage.

A brand used in more than one category, such as WAKA or Glucloud, is not assigned a product type
from the brand alone. If the product name and aisle do not resolve the family, the classifier adds
`study_type_unresolved`; the row stays in the classification file for local review and is not
silently forced into a final category.

### Product and component boundary

The final four-category table contains product observations, not an accessories inventory:

- Finished disposable vapes, pod products, e-liquids, complete device kits, and nicotine-bearing
  refill pods are included when the title supplies product evidence such as a brand, puff count,
  nicotine strength, `pod`, `refill`, or `cartucho`.
- A complete kit remains eligible when its title also mentions an integrated battery or coil.
- Standalone vape or IQOS/ILUMA device/battery bodies, chargers, coils, resistances, tanks, empty
  pods, cases, lighters, pipes, rolling papers, and other paraphernalia are excluded. An IQOS/ILUMA
  title that names the device (`dispositivo`, `device`, `body`, `holder`, or a non-welcome `kit`),
  or is a recognized bare IQOS/ILUMA model title, is `heated_device`. Accessory nouns such as
  `case` or `charger` also win over a bare `stick` mention; an inventory phrase such as “case of 10
  HEETS packs” is still a consumable. TEREA/HEETS, explicitly identified tobacco/heat sticks, and
  explicitly titled IQOS `Kit/Combo [de] Bienvenida` offers remain eligible. Welcome kits carry
  `study_heated_welcome_kit` and have no derived unit denominator.
- Snus and tobacco "tab pouch" titles are tobacco-containing oral products, not tobacco-free
  nicotine pouches. Unless the title itself says nicotine pouch, `nic pouch`, `bolsas de
  nicotina`, tobacco-free, `sin tabaco`, `libre de tabaco`, or all-white, they are retained as
  `smokeless_tobacco` in the classifications and excluded from the strict final table. An explicit
  e-liquid, pod, vape, disposable, or puff-count identity takes precedence when `snus` describes a
  vape flavour rather than an oral product.
- Gummy or edible titles (`goma`, `gomitas`, `gummies`) that carry an mg dose, or are titled as a
  gummy product, and show no independent vape identity are collisions and stay out. Independent
  evidence means an explicit vape/pod/refill/e-liquid term, a capacity stated in puffs, a generic
  liquid plus an `ml` volume, or a reviewed vape brand paired with a credible model capacity. A bare
  `mg`, `device`, `liquid`, or `10k` token is not enough. Gummy-flavour vapes with strong product
  evidence remain eligible; the reviewed “Goma Mágica” edible identity remains excluded even when
  a noisy title also contains vape-kit words.
- A context-required brand (Camel, Master, Kent, Box, ...) on a homeware or dishware title with no
  strong tobacco/nicotine product evidence is a homeware collision, flagged
  `study_homeware_collision`, and stays out. Product nouns such as `cigarrillos`, `cajetilla`,
  `vape`, `pod`, TEREA/HEETS, nicotine-pouch language, or an explicit puff capacity can establish a
  product; weak packaging/style words such as `box`, `XL`, `light`, or a bare count cannot rescue a
  mug, bowl, or plate.
- Mixed pouch-plus-beer, energy-drink, or ice bundles are excluded because neither the pack count nor
  the listed price represents the nicotine product alone.
- A title that carries two independent product-family identities (for example a Vuse Go puff count
  plus a VELO or ZYN pouch dose) joined by `+`, `combo`, `y`, or `&`, or a two-vape `de regalo`
  offer, remains a shelf-price observation with a `mixed_bundle` flag. Family identity comes from
  family-specific product words or a reviewed brand that belongs to one category only; brands
  reviewed in more than one category (WAKA, Glucloud) never establish a second family on their own.
  Because `y` often joins flavours and `&` can occur inside a brand, both sides of those ambiguous
  separators need explicit or category-corroborating product evidence. A `de regalo` offer needs a
  proved vape component on both sides of `+`; a charger or keychain gift is not a mixed product.
  The bundle's nicotine, puff, pack-count, and unit-price fields are blank because those values
  cannot be attributed to one component.
- Cannabinoid and concentrate/wax devices, insecticides using the word “vape,” gift boxes,
  cosmetics, and other observed search collisions are excluded from the requested product data.

These rules are deterministic and specific to this collection. Excluded rows remain in each
location's run-specific classification CSV, with the rule and flags that explain the decision.

## Deliverables

The exporter combines each selected location without collapsing location-specific price or
availability. The observation key is `(country_code, zone_slug, store_id, product_id)`. The runner
passes the exact collected CSV and matching classification file to export and verifies that their
key sets are identical; it does not reselect a merely newer file.

Full-protocol per-location classifications and combined outputs are written as:

- `data/<country>/processed/<zone>/classifications_<derived-run-id>.csv`
- `data/<country>/processed/combined/tobacco_items_<derived-run-id>.csv`
- `data/<country>/processed/combined/tobacco_stores_<derived-run-id>.csv`
- `data/<country>/processed/combined/locations_<derived-run-id>.csv`
- `data/<country>/processed/combined/tobacco_master_<derived-run-id>.xlsx`
- `data/<country>/processed/combined/study_manifest_<derived-run-id>.json`

All five combined artifacts share the same UTC-derived, microsecond-resolution run identifier. The
exporter reserves that identifier, stages all files under unique adjacent names, refuses to
overwrite an existing generation, and rolls back a partially finalized output set if finalization
fails.

A new processed run manifest is schema 2. It labels the run `full` or `partial` and records the
ordered queries, locations, request count, source collection manifests, row and byte counts,
SHA-256 hashes, and aggregate output counts. Every `data_root_relative_path` is a portable POSIX
path whose base is declared by `path_base: data_root`; the JSON contains no workstation or home
directory. It is separate from each location's collection-time `search_manifest_<timestamp>.json`.
Archived schema-1 processed manifests remain historical records, but new builds use schema 2.

Partial derived runs are isolated under:

```text
data/<country>/processed/diagnostic/<derived-run-id>/classifications/<zone>.csv
data/<country>/processed/diagnostic/<derived-run-id>/deliverable/tobacco_items_<derived-run-id>.csv
data/<country>/processed/diagnostic/<derived-run-id>/deliverable/tobacco_stores_<derived-run-id>.csv
data/<country>/processed/diagnostic/<derived-run-id>/deliverable/locations_<derived-run-id>.csv
data/<country>/processed/diagnostic/<derived-run-id>/deliverable/tobacco_master_<derived-run-id>.xlsx
data/<country>/processed/diagnostic/<derived-run-id>/deliverable/study_manifest_<derived-run-id>.json
```

The workbook contains `items`, `stores`, `locations`, `summary`, and `data_dictionary` sheets.
`brand_market_scope` preserves the international/local-market distinction. `unit_price_local` is
derived only when a credible pack count can be parsed. For cigarette cartons, a leading bundle count
and the ending stick count are multiplied (`10 x ... 20` means 200 sticks). A reviewed TEREA/HEETS
cajetilla is normalized to 20 sticks; an explicit carton count multiplies that denominator. A vape's
source quantity is never treated as a pack count unless the product name states the count. Puff
capacity accepts a number followed by `puffs`/`caladas`; bare `10k` or `40k` shorthand is accepted
only after the row has already been classified as a vape. Title evidence takes priority. Rappi's
structured `puffs` attribute is a fallback only for non-liquid vape rows and only above 200 through
200,000; the observed value 200 is treated as a source placeholder unless `200 puffs` appears in the
title. The dictionary describes every field in all three data sheets. Row counts are called
observations because the same product can appear at multiple stores or locations. The `summary` sheet is a compact
two-column (`metric`, `value`) inventory of build metadata and row counts; the dictionary covers the
three analytical data sheets.

When Rappi's pack metadata conflicts with the listing title and comparable prices, a narrow reviewed
title rule is used only when documented in the country note. Ambiguous rows otherwise keep a blank
pack count and unit price.

## Portable archive

`data/` is intentionally ignored by Git and can contain session state or many superseded rebuilds.
Do not force add or archive the entire directory. Stage an archive from an explicit allowlist built
from the four canonical processed manifests.

For a self-contained reproducibility archive, preserve a single `data/` tree and include exactly:

- the source item CSV, source store CSV, and collection manifest for each location;
- each complete referenced raw-response directory and all of its gzip files;
- the two tokened classification CSVs per country;
- the three output CSVs, workbook, and processed manifest per country;
- `config/study/`, the relevant documentation, and a separate code commit or version identifier;
- a package-level index naming the four canonical processed manifests and declaring that their
  paths resolve beneath the packaged `data/` directory.

Exclude `.env`, cookies, tokens, `data/state`, browser/session data, checkpoints, `.partial` or
temporary files, diagnostic runs, and superseded generations. Normalize shared files to mode 0644
and directories to 0755 in the staged copy, and reject absolute or traversal archive member names.
Verify every manifest-recorded byte count, SHA-256 hash, and CSV row count after staging and again
after extracting the archive. If only the analytical outputs are shared, label the package
“outputs only”; do not describe it as self-contained while its manifest input paths are absent.

## Run sequence

Install and validate:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m pytest tests -q
python -m rappi_co.study --all-countries --dry-run
```

Run one request at every configured location before a full pass:

```bash
python -m rappi_co.study --all-countries --terms cigarrillos --collect-only
```

For a tobacco-term pilot, use a dated output directory so diagnostic files do
not mix with a later release:

```bash
python -m rappi_co.study --country mx --terms "new term" \
  --data-root data/pilots/tobacco_term_check_YYYYMMDD
```

Inspect the item and store counts. If every location is healthy, run one country at a time:

```bash
python -m rappi_co.study --country ar
python -m rappi_co.study --country co
python -m rappi_co.study --country pe
python -m rappi_co.study --country mx
```

To rebuild classification and deliverables from existing search files without network access:

```bash
python -m rappi_co.study --country pe --skip-collect
```

`--skip-collect` requires a successful collection manifest whose ordered queries exactly match the
requested run. With no `--terms`, that means the complete default country query list. Passing the
same diagnostic `--terms` rebuilds that partial run only under `processed/diagnostic/`; it cannot
write the normal per-zone or combined paths. `--collect-only` creates raw collection artifacts and
no processed manifest. This prevents a newer one query file from being treated as a full collection.

## Interpretation limits

- Results describe Rappi visibility at eight sampled delivery points, not national retail markets.
- A query returning no product does not establish that the category or brand is absent nationally.
- An indexed or returned listing does not establish that a product is available, registered, or
  lawfully sold.
- Rank observed brands only after collection, using transparent measures such as distinct products,
  distinct stores, and location coverage.
- Regulatory notes are collection context, not legal advice. Recheck official sources immediately
  before each collection wave.
