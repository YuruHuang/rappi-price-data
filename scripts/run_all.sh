#!/usr/bin/env bash
# overnight self-healing crawl for one delivery address.
# rappi rate-limits / 403-blocks heavy crawling, so this loops with long naps: it
# enumerates the store list if we don't have a full one yet, then crawls every store's
# full catalog. each attempt resumes via the scrapy jobdir, so a temporary block just
# means "try again next loop". safe to ctrl-c and re-run.
#
# usage:  scripts/run_all.sh <address-slug> [iterations] [nap_secs]
#   e.g.  scripts/run_all.sh calle-19-centro
# run one address per invocation (don't hammer two at once).
set -euo pipefail
addr="${1:?usage: scripts/run_all.sh <address-slug> [iterations] [nap_secs]}"
iters="${2:-24}"
nap="${3:-300}"
dir="data/raw/$addr"
log="$dir/_run_all.log"
mkdir -p "$dir"

have_stores() {  # true if a real enumeration (>200 rows) already exists
  for f in "$dir"/stores_*.csv; do
    [ -f "$f" ] && [ "$(wc -l < "$f")" -gt 200 ] && return 0
  done
  return 1
}

for i in $(seq 1 "$iters"); do
  echo "=== $addr iter $i/$iters $(date '+%F %H:%M:%S') ===" | tee -a "$log"
  if ! have_stores; then
    echo "[$addr] enumerating stores" | tee -a "$log"
    if ! RAPPI_ADDRESS="$addr" scrapy crawl stores >> "$log" 2>&1; then
      echo "[$addr] store enumeration attempt failed; retrying after nap" | tee -a "$log"
    fi
  fi
  if have_stores; then
    echo "[$addr] crawling menu (resumes via jobdir)" | tee -a "$log"
    if ! RAPPI_ADDRESS="$addr" scrapy crawl menu >> "$log" 2>&1; then
      echo "[$addr] menu crawl attempt failed; retrying after nap" | tee -a "$log"
    fi
  else
    echo "[$addr] no stores yet (blocked?) — retrying after nap" | tee -a "$log"
  fi
  sleep "$nap"
done
if ! have_stores; then
  echo "=== $addr failed: no complete store enumeration after $iters attempts ===" | tee -a "$log"
  exit 1
fi
echo "=== $addr attempts complete — verify with: RAPPI_ADDRESS=$addr python -m rappi_co.checks --stage all ===" | tee -a "$log"
