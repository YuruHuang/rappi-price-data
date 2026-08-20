#!/usr/bin/env bash
# crawl every address in config/zones_co.yml, one at a time.
# each address has its own locked session + output dir, so scrapy runs once per address
# (there is no single "all addresses" run). back-to-back crawls can trip rappi's per-IP
# rate limit, so we pause between addresses — run this off-peak.
#
# prereq: python -m rappi_co.bootstrap --all   (locks each address first)
# usage:  scripts/crawl_all.sh
set -euo pipefail
addrs=$(python -c "import yaml; print(' '.join(z['slug'] for z in yaml.safe_load(open('config/zones_co.yml'))['zones']))")
for a in $addrs; do
  echo "=== $a: stores ==="; RAPPI_ADDRESS="$a" scrapy crawl stores
  echo "=== $a: menu ===";   RAPPI_ADDRESS="$a" scrapy crawl menu
  echo "=== $a done — pausing 5m so the IP cools before the next address ==="
  sleep 300
done
echo "all addresses done."
