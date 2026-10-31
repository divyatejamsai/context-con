#!/usr/bin/env bash
# Real-hires backtest with an untouched test window.
#   dev  = Jun-Dec 2025 postings: used to diagnose Sourced and fit the likelihood-to-move weights (5-fold CV)
#   test = Jan-Apr 2026 postings: never looked at; Sourced before vs after, weights from dev only
# Writes ../docs/BACKTEST_dev.md, ../docs/BACKTEST_test_before.md, ../docs/BACKTEST_test_after.md (no person names).
set -euo pipefail
# Resumable: Crustdata responses are cached (CRUSTDATA_MODE=cache) and finished openings in each tag's results.jsonl
# are kept, so after a stop (e.g. out of credits: the run exits on the first 402) just run this script again.
# Use --fresh by hand only after changing Sourced's code.
export CRUSTDATA_MODE=${CRUSTDATA_MODE:-cache}
cd "$(dirname "$0")/.."
BT="python -m evals.backtest"
ZERO='{"sweet_spot":0,"due":0,"just_moved":0,"between_jobs":0,"step_up":0,"overqualified":0,"adjacent_title":0}'

echo "== dev: Jun-Dec 2025 (current Sourced, move weights off, then tuned with CV)"
RANK_MOVE_WEIGHTS="$ZERO" $BT all --tag dev --start 2025-06-01 --end 2025-12-31 --job-limit 400 --max-jobs 150 --target 60 \
  --out ../docs/BACKTEST_dev.md | tail -40
W=$(python -c "import json;print(json.dumps({k:v for k,v in json.load(open('data/backtest/dev/tune.json'))['weights'].items()}))")
echo "dev-fitted move weights: $W"

echo "== test openings: Jan-Apr 2026"
$BT openings --tag test --start 2026-01-01 --end 2026-04-30 --job-limit 400 --max-jobs 150 --target 60 | tail -5

echo "== test, BEFORE: Sourced as of PR #17 (no talent flow, no step-down search, old seniority credit, no move bonus)"
TALENT_FLOW=0 SEARCH_STEP_DOWN=0 RANK_STEP_DOWN_CREDIT=0.6 RANK_MOVE_WEIGHTS="$ZERO" \
  $BT run --tag test-before --openings-from test | tail -3
$BT score --tag test-before --out ../docs/BACKTEST_test_before.md | sed -n '1,25p'

echo "== test, AFTER: talent flow + step-down search + seniority credit + dev-fitted move weights"
RANK_MOVE_WEIGHTS="$W" $BT run --tag test-after --openings-from test | tail -3
$BT score --tag test-after --out ../docs/BACKTEST_test_after.md | sed -n '1,25p'
echo "weights used on test: $W"
