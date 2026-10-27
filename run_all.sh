#!/usr/bin/env bash
# One command: generate -> validate -> evaluate -> reproducibility proof (stdlib-only Python 3.9+)
set -euo pipefail
cd "$(dirname "$0")"
SEED=${SEED:-20261022}
for P in starter full; do
  python3 generate.py --profile "$P" --seed "$SEED" --out "data/$P"
  python3 validate.py --data "data/$P" > "data/$P/reports/validation_console.txt"
  python3 evaluate.py --data "data/$P" > "data/$P/reports/evaluation_console.txt"
  python3 repro_check.py --profile "$P" --seed "$SEED" --compare "data/$P" --report "data/$P/reports/reproducibility_report.json" \
      > "data/$P/reports/reproducibility_console.txt"
  tail -n 3 "data/$P/reports/reproducibility_console.txt"
done
python3 schema.py --write docs
echo "ALL DONE"
