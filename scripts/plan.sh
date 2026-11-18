#!/usr/bin/env bash
# Write the deployment plan for one target to plan-<target>.json and list the planned actions
# (in the log and, on GitHub Actions, in the job summary). Deploy exactly this plan with:
#   databricks bundle deploy --target <target> --plan plan-<target>.json --auto-approve
#   scripts/plan.sh <dev|staging|prod> [extra bundle options]
set -euo pipefail
TARGET="${1:?usage: plan.sh <target> [bundle options]}"
shift
cd "$(dirname "$0")/.."
command -v jq >/dev/null || { echo "plan.sh needs jq: https://jqlang.org/download/"; exit 1; }

databricks bundle plan --target "$TARGET" "$@" --output json > "plan-$TARGET.json"
ACTIONS=$(jq -r '.plan // {} | to_entries[] | "| \(.key) | \(.value.action) |"' "plan-$TARGET.json")

echo "Plan for $TARGET:"
echo "${ACTIONS:-no changes}"
if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  { echo "### Deployment plan: $TARGET"; echo; echo "| Resource | Action |"; echo "|---|---|"; echo "$ACTIONS"; echo; } >> "$GITHUB_STEP_SUMMARY"
fi
