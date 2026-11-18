"""Genie Agent benchmark gate.

Runs every benchmark question of a Genie Agent, waits for the evaluation, and passes only when
accuracy is above --min-accuracy. On failure it prints each failing question with the reason
Genie's evaluator gave, then raises, so the job run fails and Databricks sends the failure email.

Runs as a Databricks job task (resources/benchmark_gate.job.yml) or locally:
    python src/benchmark_gate.py --space-id <id> --min-accuracy 80
Uses the Genie benchmark evaluation API (Beta).
"""
import argparse
import json
import time

FINAL = {"DONE", "EVALUATION_FAILED", "EVALUATION_CANCELLED", "EVALUATION_TIMEOUT"}

REASONS = {
    "EMPTY_RESULT": "the query returned no rows",
    "EMPTY_GOOD_SQL": "the expected SQL returned no rows",
    "RESULT_MISSING_ROWS": "rows are missing compared with the expected result",
    "RESULT_EXTRA_ROWS": "there are extra rows compared with the expected result",
    "RESULT_MISSING_COLUMNS": "columns are missing compared with the expected result",
    "RESULT_EXTRA_COLUMNS": "there are extra columns compared with the expected result",
    "SINGLE_CELL_DIFFERENCE": "a value differs from the expected result",
    "COLUMN_TYPE_DIFFERENCE": "a column has a different type than expected",
    "LLM_JUDGE_MISSING_OR_INCORRECT_FILTER": "a filter is missing or wrong",
    "LLM_JUDGE_WRONG_FILTER": "a filter is wrong",
    "LLM_JUDGE_MISSING_OR_INCORRECT_AGGREGATION": "an aggregation is missing or wrong",
    "LLM_JUDGE_WRONG_AGGREGATION": "an aggregation is wrong",
    "LLM_JUDGE_MISSING_OR_INCORRECT_JOIN": "a join is missing or wrong",
    "LLM_JUDGE_MISSING_JOIN": "a join is missing",
    "LLM_JUDGE_INCORRECT_TABLE_OR_FIELD_USAGE": "the wrong table or column was used",
    "LLM_JUDGE_WRONG_COLUMNS": "the wrong columns were returned",
    "LLM_JUDGE_INCORRECT_METRIC_CALCULATION": "a metric is calculated incorrectly",
    "LLM_JUDGE_INCORRECT_FUNCTION_USAGE": "a function is used incorrectly",
    "LLM_JUDGE_INSTRUCTION_COMPLIANCE_OR_MISSING_BUSINESS_LOGIC": "business logic or an instruction was not followed",
    "LLM_JUDGE_MISINTERPRETATION_OF_USER_REQUEST": "the question was misinterpreted",
    "LLM_JUDGE_INCOMPLETE_OR_PARTIAL_OUTPUT": "the answer is incomplete",
    "LLM_JUDGE_FORMATTING_ERROR": "the output is formatted incorrectly",
    "LLM_JUDGE_SEMANTIC_ERROR": "the SQL has a semantic error",
    "LLM_JUDGE_SYNTAX_ERROR": "the SQL has a syntax error",
    "LLM_JUDGE_OTHER": "the evaluator flagged another problem",
}


def response_text(responses):
    """First non-empty response (Genie's SQL or text), on one line."""
    for r in responses or []:
        if r.get("response"):
            return " ".join(str(r["response"]).split())
    return ""


def failure(result, details):
    """A failing benchmark question as a printable record, or None when the answer was correct."""
    assessment = details.get("assessment", "NEEDS_REVIEW")
    if assessment == "GOOD":
        return None
    reasons = [REASONS.get(x, x) for x in details.get("assessment_reasons", [])]
    if not reasons:
        reasons = ["needs manual review"] if assessment == "NEEDS_REVIEW" else ["no reason given"]
    return {
        "question": result.get("question", ""),
        "assessment": assessment,
        "reasons": reasons,
        "genie_sql": response_text(details.get("actual_response"))[:400],
    }


def evaluate(run, failures, min_accuracy):
    """Decide the gate from a finished eval run. Answers that need review count as not correct.
    Passes only when the run finished and accuracy is strictly above min_accuracy."""
    status = run.get("eval_run_status", "NOT_STARTED")
    total = int(run.get("num_questions") or 0)
    correct = int(run.get("num_correct") or 0)
    accuracy = 100.0 * correct / total if total else 0.0
    passed = status == "DONE" and total > 0 and accuracy > min_accuracy
    if status != "DONE":
        why = f"benchmark run ended with status {status}"
    elif total == 0:
        why = "the agent has no benchmark questions"
    else:
        why = f"accuracy {accuracy:.1f}% ({correct}/{total}) is not above {min_accuracy:g}%"
    return {"passed": passed, "accuracy": round(accuracy, 1), "correct": correct, "total": total,
            "min_accuracy": min_accuracy, "status": status, "reason": None if passed else why, "failures": failures}


def report(name, target, run_id, s):
    lines = ["", "=" * 72, f"GENIE BENCHMARK GATE  {'PASSED' if s['passed'] else 'FAILED'}",
             f"Agent: {name}   Target: {target}   Run: {run_id}",
             f"Accuracy: {s['accuracy']:.1f}% ({s['correct']}/{s['total']} correct)   Required: above {s['min_accuracy']:g}%",
             "=" * 72]
    for i, f in enumerate(s["failures"], 1):
        lines.append(f"{i:>2}. [{f['assessment']}] {f['question']}")
        lines.append(f"    Reason: {'; '.join(f['reasons'])}")
        if f["genie_sql"]:
            lines.append(f"    Genie answered: {f['genie_sql']}")
    return "\n".join(lines)


def run_benchmarks(api, space_id, timeout_minutes):
    """Start an eval run over all benchmarks, wait for it, and return (run, results)."""
    base = f"/api/2.0/genie/spaces/{space_id}/eval-runs"
    run_id = api.do("POST", base, body={})["eval_run_id"]
    print(f"Benchmark run {run_id} started", flush=True)
    deadline, delay = time.time() + timeout_minutes * 60, 5
    while True:
        run = api.do("GET", f"{base}/{run_id}")
        status = run.get("eval_run_status", "NOT_STARTED")
        print(f"  {status}: {run.get('num_done', 0)}/{run.get('num_questions', '?')} questions evaluated", flush=True)
        if status in FINAL:
            break
        if time.time() > deadline:
            raise RuntimeError(f"Benchmark run {run_id} did not finish within {timeout_minutes} minutes")
        time.sleep(delay)
        delay = min(delay * 2, 60)
    results, token = [], None
    while True:
        query = {"page_size": 100, **({"page_token": token} if token else {})}
        page = api.do("GET", f"{base}/{run_id}/results", query=query)
        results += page.get("eval_results", [])
        token = page.get("next_page_token")
        if not token:
            break
    failures = [f for f in (failure(r, api.do("GET", f"{base}/{run_id}/results/{r['result_id']}")) for r in results) if f]
    return run_id, run, failures


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--space-id", required=True)
    p.add_argument("--min-accuracy", type=float, default=80.0, help="accuracy must be above this percentage")
    p.add_argument("--target", default="")
    p.add_argument("--timeout-minutes", type=int, default=45)
    a = p.parse_args()

    from databricks.sdk import WorkspaceClient  # imported here so the unit tests do not need the SDK

    api = WorkspaceClient().api_client
    name = api.do("GET", f"/api/2.0/genie/spaces/{a.space_id}").get("title", a.space_id)
    print(f"Agent: {name} ({a.target or 'no target'})", flush=True)
    run_id, run, failures = run_benchmarks(api, a.space_id, a.timeout_minutes)
    s = evaluate(run, failures, a.min_accuracy)
    print(report(name, a.target, run_id, s))
    print("GATE_RESULT_JSON " + json.dumps({**s, "eval_run_id": run_id, "space_id": a.space_id, "target": a.target}), flush=True)
    if not s["passed"]:
        top = "; ".join(f"'{f['question']}': {', '.join(f['reasons'])}" for f in failures[:10])
        raise RuntimeError(f"Genie benchmark gate failed for '{name}' in {a.target}: {s['reason']}. Failing questions: {top}")


if __name__ == "__main__":
    main()
