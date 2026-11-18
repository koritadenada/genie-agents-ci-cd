#!/usr/bin/env bash
# Run the benchmark gate job for one target, print its report, and exit non-zero when it fails.
#   scripts/run_gate.sh <dev|staging|prod> [extra bundle options, for example --var warehouse_id=<id>]
# The job itself emails var.alert_email on failure; this script makes the reasons visible in CI
# (log and, on GitHub Actions, the job summary).
set -uo pipefail
TARGET="${1:?usage: run_gate.sh <target> [bundle options]}"
shift
cd "$(dirname "$0")/.."
command -v jq >/dev/null || { echo "run_gate.sh needs jq: https://jqlang.org/download/"; exit 1; }

JOB_ID=$(databricks bundle summary -t "$TARGET" "$@" -o json | jq -r '.resources.jobs.benchmark_gate.id')
[ -n "$JOB_ID" ] && [ "$JOB_ID" != "null" ] || { echo "benchmark_gate job not deployed for $TARGET"; exit 1; }

echo "Running the benchmark gate (job $JOB_ID) on $TARGET ..."
# Keep the run output out of the log here: the report is printed once, below, from the task output.
RUN_LOG=$(mktemp)
databricks bundle run benchmark_gate -t "$TARGET" "$@" > "$RUN_LOG" 2>&1
RC=$?
grep -E '^(Run URL|[0-9]{4}-[0-9]{2}-[0-9]{2} )' "$RUN_LOG"

# Print the task output (report, failing questions and reasons) whether the run passed or failed.
# The run ID comes from this run's URL, so a concurrent run of the same job cannot be picked up by mistake.
RUN_ID=$(sed -n 's#^Run URL: .*/runs/\([0-9][0-9]*\).*#\1#p' "$RUN_LOG" | head -1)
if [ -z "$RUN_ID" ]; then
  echo "The benchmark gate run did not start:"; cat "$RUN_LOG"; exit 1
fi
RUN=$(databricks jobs get-run "$RUN_ID" -o json)
TASK_RUN_ID=$(echo "$RUN" | jq -r '.tasks[0].run_id')
# Pass only when Databricks reports the run itself as successful, whatever the CLI's exit code was.
if [ "$(echo "$RUN" | jq -r '.state.result_state // empty')" != "SUCCESS" ] && [ "$RC" -eq 0 ]; then RC=1; fi
OUT=$(databricks jobs get-run-output "$TASK_RUN_ID" -o json)
LOGS=$(echo "$OUT" | jq -r '.logs // ""')
echo "$LOGS" | grep -v '^GATE_RESULT_JSON '
echo "$OUT" | jq -r '.error // empty'

RESULT=$(echo "$LOGS" | sed -n 's/^GATE_RESULT_JSON //p' | tail -1)
if [ -n "${GITHUB_STEP_SUMMARY:-}" ] && [ -n "$RESULT" ]; then
  {
    echo "### Genie benchmark gate: $TARGET"
    echo "$RESULT" | jq -r '"**\(if .passed then "Passed" else "Failed" end)**: accuracy \(.accuracy)% (\(.correct)/\(.total)), required above \(.min_accuracy)%"'
    echo
    echo "$RESULT" | jq -r 'if .reason then "Reason: \(.reason)\n" else empty end'
    echo "$RESULT" | jq -r 'if (.failures|length) > 0 then "| Question | Assessment | Reason |\n|---|---|---|"
                            elif .passed then "All benchmark questions passed." else empty end'
    echo "$RESULT" | jq -r 'def cell: gsub("\\|"; "\\|") | gsub("\n"; " ");
                            .failures[] | "| \(.question|cell) | \(.assessment) | \(.reasons|join("; ")|cell) |"'
  } >> "$GITHUB_STEP_SUMMARY"
fi

if [ "$RC" -ne 0 ]; then
  echo "Benchmark gate failed on $TARGET: the team was emailed and the pipeline stops here."
fi
exit "$RC"
