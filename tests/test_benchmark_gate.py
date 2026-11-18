from benchmark_gate import evaluate, failure, report


def run(status="DONE", total=20, correct=20):
    return {"eval_run_status": status, "num_questions": total, "num_correct": correct}


def test_passes_above_threshold():
    s = evaluate(run(correct=17), [], 80)
    assert s["passed"] and s["accuracy"] == 85.0 and s["reason"] is None


def test_exactly_the_threshold_fails():
    s = evaluate(run(correct=16), [], 80)
    assert not s["passed"]
    assert s["reason"] == "accuracy 80.0% (16/20) is not above 80%"


def test_unfinished_run_fails_even_at_full_accuracy():
    s = evaluate(run(status="EVALUATION_FAILED", correct=20), [], 80)
    assert not s["passed"] and "EVALUATION_FAILED" in s["reason"]


def test_no_benchmarks_fails():
    s = evaluate(run(total=0, correct=0), [], 80)
    assert not s["passed"] and s["reason"] == "the agent has no benchmark questions"


def test_correct_answer_is_not_a_failure():
    assert failure({"question": "q"}, {"assessment": "GOOD"}) is None


def test_failure_maps_reason_codes_and_keeps_genie_sql():
    f = failure({"question": "Revenue in 2025?"},
                {"assessment": "BAD", "assessment_reasons": ["SINGLE_CELL_DIFFERENCE", "SOMETHING_NEW"],
                 "actual_response": [{"response": "SELECT\n  SUM(x)\nFROM t"}]})
    assert f["reasons"] == ["a value differs from the expected result", "SOMETHING_NEW"]
    assert f["genie_sql"] == "SELECT SUM(x) FROM t"


def test_needs_review_without_reasons():
    f = failure({"question": "q"}, {"assessment": "NEEDS_REVIEW"})
    assert f["reasons"] == ["needs manual review"]


def test_report_lists_failures():
    f = failure({"question": "Revenue in 2025?"}, {"assessment": "BAD", "assessment_reasons": ["EMPTY_RESULT"]})
    text = report("Sales Analytics", "staging", "run-1", evaluate(run(correct=16), [f], 80))
    assert "GENIE BENCHMARK GATE  FAILED" in text
    assert "1. [BAD] Revenue in 2025?" in text and "the query returned no rows" in text
