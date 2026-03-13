#!/bin/bash
##########################################################################################
# jenkins_bug_report.sh
#
# Jenkins pipeline script that:
#   1. Sources credentials from $ENV_FILE
#   2. Creates/activates a Python virtualenv
#   3. Runs the bug-report workflow via pm_agent.py
#   4. Renames the output .xlsx file to include today's date
#
# Usage (Jenkins freestyle job):
#   ENV_FILE=/path/to/secret/.env ./jenkins_bug_report.sh
##########################################################################################
set -euo pipefail

ifconfig

# Source the secret .env file directly instead of copying
# (avoids permission issues with cp in the workspace)
set -a
source "$ENV_FILE"
set +a

# Create virtualenv if it doesn't exist
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi

# Debug: check LLM connectivity
echo "Testing LLM connectivity..."
echo "CORNELIS_LLM_BASE_URL=$CORNELIS_LLM_BASE_URL"
echo "CORNELIS_LLM_MODEL=$CORNELIS_LLM_MODEL"
curl -s --connect-timeout 5 "$CORNELIS_LLM_BASE_URL/models" || echo "FAILED: Cannot reach LLM endpoint"

source .venv/bin/activate
pip install --upgrade pip
pip install ".[agents]"

echo "======"
python3 --version
echo "======"

python3 pm_agent.py \
    --workflow bug-report \
    --filter "SW 12.1.1 P0/P1 Bugs" \
    --model developer-opus \
    --d-columns Phase Customer Product Module Priority \
    --timeout 800 \
    --verbose

# Append today's date to each .xlsx file produced by the workflow.
# e.g. sw_1211_p0p1_bugs.xlsx  ->  sw_1211_p0p1_bugs_2026-02-19.xlsx
TODAY="$(date '+%Y-%m-%d')"
for xlsx in *.xlsx; do
    [ -f "$xlsx" ] || continue
    base="${xlsx%.xlsx}"
    dated="${base}_${TODAY}.xlsx"
    echo "Renaming: $xlsx -> $dated"
    mv "$xlsx" "$dated"
done
