#!/usr/bin/env bash
##########################################################################################
# run_bug_report.sh
#
# Hardened pipeline script that:
#   1. Looks up a Jira filter by name from the user's favourite filters
#   2. Runs the filter to pull tickets with latest comments
#   3. Sends the JSON to the LLM agent with the cn5000_bugs_clean prompt
#   4. Converts the resulting CSV report to a styled Excel workbook
#
# Usage:
#   ./run_bug_report.sh "SW 12.1.1 P0/P1 Bugs"
#   ./run_bug_report.sh "My Filter Name"
#
# Prerequisites:
#   - Python 3 virtual-env activated (with jira, openpyxl, etc.)
#   - .env or .env_prod loaded with JIRA_URL, JIRA_USER, JIRA_TOKEN, LLM vars
##########################################################################################
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration — edit these if prompt or filenames change
# ---------------------------------------------------------------------------
readonly PROMPT="agents/prompts/cn5000_bugs_clean.md"
readonly LLM_TIMEOUT=800
readonly CSV_OUTPUT="cn_bug_report.csv"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log()  { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
die()  { log "FATAL: $*" >&2; exit 1; }
hr()   { printf '%.0s─' {1..72}; printf '\n'; }

# Verify a command exists on PATH
require_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

# Verify a file exists and is non-empty
require_file() {
    [[ -f "$1" ]] || die "Expected file not found: $1"
    [[ -s "$1" ]] || die "File exists but is empty: $1"
}

# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------
usage() {
    cat <<EOF
Usage: $(basename "$0") "FILTER_NAME"

  FILTER_NAME   Exact name of a Jira filter (e.g. "SW 12.1.1 P0/P1 Bugs")

The script looks up the filter ID from your filters, runs it to
pull tickets with latest comments, sends the JSON through the LLM agent,
and converts the resulting CSV to a styled Excel workbook.
EOF
    exit 1
}

# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------
[[ $# -lt 1 ]] && usage
readonly FILTER_NAME="$1"

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
log "Pre-flight checks..."
require_cmd python3

# Ensure we are in the project directory (script may be invoked from elsewhere)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Verify key source files exist
require_file "jira_utils.py"
require_file "pm_agent.py"
require_file "excel_utils.py"
require_file "$PROMPT"

log "All pre-flight checks passed."
log "Filter name: \"${FILTER_NAME}\""
hr

# ---------------------------------------------------------------------------
# Step 1: Look up filter ID from favourite filters
# ---------------------------------------------------------------------------
log "Step 1/4: Looking up filter ID for \"${FILTER_NAME}\" ..."

# Run --list-filters --favourite. Show all output on stdout in real time,
# and capture it for parsing. We use a temp file + tee so output streams live.
FILTER_TMPFILE="$(mktemp)"
trap 'rm -f "$FILTER_TMPFILE"' EXIT
python3 jira_utils.py --list-filters --favourite 2>&1 | tee "$FILTER_TMPFILE" || true
FILTER_OUTPUT="$(cat "$FILTER_TMPFILE")"

if [[ -z "$FILTER_OUTPUT" ]]; then
    die "Failed to retrieve filters from Jira"
fi

# Extract the filter ID by matching the filter name.
# The Python format string is: f'{fid:<10} {fname:<35} {owner:<25} {fav:<5} {jql:<60}'
# So: columns 1-10 = ID (left-padded), col 11 = space, columns 12-46 = Name (35 chars).
# Only process lines whose first token is a numeric ID (skip log lines, headers, etc.)
FILTER_ID=""
while IFS= read -r line; do
    # Extract the first whitespace-delimited token
    local_id="$(echo "$line" | awk '{print $1}')"

    # Only process lines where the first token is a pure numeric filter ID
    [[ "$local_id" =~ ^[0-9]+$ ]] || continue

    # Name field: columns 12-46 (1-indexed). Trim trailing whitespace.
    local_name="$(echo "$line" | cut -c12-46 | sed 's/[[:space:]]*$//')"

    # Debug: show what we parsed (only visible with bash -x)
    log "  Parsed: id=${local_id} name=\"${local_name}\""

    # Match: exact match
    if [[ "$local_name" == "$FILTER_NAME" ]]; then
        FILTER_ID="$local_id"
        break
    fi

    # Handle truncated names: if the filter name is longer than 33 chars,
    # the display truncates to 33 chars + '..'
    if [[ ${#FILTER_NAME} -gt 33 ]]; then
        truncated="${FILTER_NAME:0:33}.."
        if [[ "$local_name" == "$truncated" ]]; then
            FILTER_ID="$local_id"
            break
        fi
    fi

    # Also try a substring match for robustness (name starts with the displayed text)
    # Strip any trailing '..' from local_name for prefix matching
    local_name_clean="${local_name%..}"
    if [[ -n "$local_name_clean" ]] && [[ "$FILTER_NAME" == "$local_name_clean"* ]]; then
        FILTER_ID="$local_id"
        break
    fi
done <<< "$FILTER_OUTPUT"

# Validate we found a numeric filter ID
if [[ -z "$FILTER_ID" ]]; then
    log "Available favourite filters:"
    echo "$FILTER_OUTPUT"
    die "Filter \"${FILTER_NAME}\" not found in favourite filters"
fi

if ! [[ "$FILTER_ID" =~ ^[0-9]+$ ]]; then
    die "Parsed filter ID is not numeric: \"${FILTER_ID}\""
fi

log "Step 1/4 complete — Filter ID: ${FILTER_ID}"
hr

# ---------------------------------------------------------------------------
# Step 2: Run the filter to pull tickets with latest comments
# ---------------------------------------------------------------------------
# Derive a safe dump filename from the filter name (lowercase, spaces → underscores)
DUMP_FILE="$(echo "$FILTER_NAME" | tr '[:upper:]' '[:lower:]' | tr ' ' '_' | tr -cd 'a-z0-9_-')"
[[ -z "$DUMP_FILE" ]] && DUMP_FILE="filter_${FILTER_ID}"

log "Step 2/4: Running filter ${FILTER_ID} → ${DUMP_FILE}.json ..."

python3 jira_utils.py \
    --run-filter "$FILTER_ID" \
    --dump-file  "$DUMP_FILE" \
    --get-comments latest

require_file "${DUMP_FILE}.json"
log "Step 2/4 complete — $(wc -l < "${DUMP_FILE}.json" | tr -d ' ') lines in ${DUMP_FILE}.json"
hr

# ---------------------------------------------------------------------------
# Step 3: Invoke LLM agent with the bug-clean prompt + JSON attachment
# ---------------------------------------------------------------------------
log "Step 3/4: Invoking LLM agent (timeout=${LLM_TIMEOUT}s) ..."

python3 pm_agent.py \
    --invoke-llm "$PROMPT" \
    --attachments "${DUMP_FILE}.json" \
    --timeout "$LLM_TIMEOUT" \
    --verbose

# The LLM agent saves extracted files (e.g. cn_bug_report.csv) and llm_output.md
if [[ -f "llm_output.md" ]]; then
    log "Step 3/4 complete — llm_output.md saved"
else
    log "WARNING: llm_output.md not found (LLM may not have produced output)"
fi
hr

# ---------------------------------------------------------------------------
# Step 4: Convert CSV report to styled Excel workbook
# ---------------------------------------------------------------------------
if [[ -f "$CSV_OUTPUT" ]]; then
    log "Step 4/4: Converting ${CSV_OUTPUT} → Excel ..."

    python3 excel_utils.py --convert-from-csv "$CSV_OUTPUT"

    # Derive expected xlsx name
    XLSX_OUTPUT="${CSV_OUTPUT%.csv}.xlsx"
    if [[ -f "$XLSX_OUTPUT" ]]; then
        log "Step 4/4 complete — ${XLSX_OUTPUT} ($(du -h "$XLSX_OUTPUT" | cut -f1))"
    else
        log "WARNING: Expected ${XLSX_OUTPUT} not found after conversion"
    fi
else
    log "Step 4/4: SKIPPED — ${CSV_OUTPUT} not found (LLM may not have produced it)"
    log "Check llm_output.md and llm_output_file* for extracted content."
fi
hr

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
log "Pipeline complete. Filter: \"${FILTER_NAME}\" (ID: ${FILTER_ID})"
log "Output files:"
for f in "${DUMP_FILE}.json" llm_output.md "$CSV_OUTPUT" "${CSV_OUTPUT%.csv}.xlsx" llm_output_file*; do
    if [[ -f "$f" ]]; then
        printf '  ✓ %-35s %s\n' "$f" "$(du -h "$f" | cut -f1)"
    fi
done
