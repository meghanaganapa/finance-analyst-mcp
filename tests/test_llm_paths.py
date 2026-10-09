import json

from finance_analyst.llm import parse_reply

GOOD = ("SELECT r.region_name, ROUND(SUM(ol.quantity * ol.unit_price * (1 - ol.discount)), 2) AS revenue "
        "FROM orders o JOIN order_lines ol ON ol.order_id = o.order_id "
        "JOIN customers c ON c.customer_id = o.customer_id JOIN regions r ON r.region_id = c.region_id "
        "WHERE o.status = 'completed' AND substr(o.order_date, 1, 4) = '2025' GROUP BY r.region_name")


def reply(sql):
    return json.dumps({"sql": sql})


def test_llm_sql_is_used_and_cross_checked(make_llm_assistant):
    a, llm = make_llm_assistant(reply(GOOD))
    ans = a.ask("Revenue by region for 2025")
    assert ans.status == "answered" and ans.backend == "fake:test"
    assert ans.llm_usage["input_tokens"] == 100


def test_unsafe_llm_sql_is_blocked_then_repaired(make_llm_assistant):
    a, llm = make_llm_assistant(reply("SELECT * FROM employees"), reply(GOOD))
    ans = a.ask("Revenue by region for 2025")
    assert ans.status == "answered"
    assert "sensitive_table" in llm.prompts[1]  # the guard's reason was fed back
    assert [s.step for s in ans.trace].count("guard") == 2


def test_llm_cannot_answer_means_abstain(make_llm_assistant):
    a, _ = make_llm_assistant(json.dumps({"cannot_answer": "no forecast data"}))
    ans = a.ask("What will Q1 2026 revenue look like?")
    assert ans.status == "abstained" and "forecast" in ans.answer


def test_llm_failure_falls_back_to_offline_with_review(make_llm_assistant):
    a, _ = make_llm_assistant(TimeoutError("network down"))
    ans = a.ask("What was total revenue in 2025?")
    assert ans.status == "needs_review"
    assert any("offline semantic layer" in r for r in ans.review_reasons)
    assert ans.result.rows[0][0] > 0


def test_disagreement_with_semantic_layer_goes_to_review(make_llm_assistant):
    wrong = GOOD.replace("o.status = 'completed'", "o.status <> 'cancelled'")  # includes returns
    a, _ = make_llm_assistant(reply(wrong))
    ans = a.ask("Revenue by region for 2025")
    assert ans.status == "needs_review"
    assert any("semantic layer" in r for r in ans.review_reasons)


def test_parse_reply_tolerates_code_fences_and_prose():
    assert parse_reply('Sure!\n```json\n{"sql": "SELECT 1"}\n```')["sql"] == "SELECT 1"
