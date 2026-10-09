def test_answers_and_matches_the_database(assistant):
    ans = assistant.ask("What was total revenue in 2025?")
    expected = assistant.con.execute(
        "SELECT ROUND(SUM(ol.quantity * ol.unit_price * (1 - ol.discount)), 2) FROM orders o "
        "JOIN order_lines ol ON ol.order_id = o.order_id WHERE o.status = 'completed' "
        "AND substr(o.order_date, 1, 4) = '2025'").fetchone()[0]
    assert ans.status == "answered"
    assert ans.result.rows[0][0] == expected


def test_refuses_hr_question_before_touching_the_database(assistant):
    ans = assistant.ask("Who is the highest paid employee?")
    assert ans.status == "refused" and ans.sql is None
    assert [s.step for s in ans.trace] == ["policy"]


def test_trace_records_every_step(assistant):
    ans = assistant.ask("Revenue vs budget by region for 2025")
    assert [s.step for s in ans.trace] == ["policy", "planner:offline", "guard", "executor", "reviewer"]
    assert ans.result.columns == ["region_name", "revenue", "budget", "variance"]


def test_partly_understood_question_goes_to_review(assistant):
    ans = assistant.ask("Total sales for calendar year 2025, please.")
    assert ans.status == "needs_review" and "calendar" in ans.review_reasons[0]


def test_run_sql_tool_blocks_and_allows(assistant):
    assert assistant.run_sql("SELECT * FROM employees")["allowed"] is False
    ok = assistant.run_sql("SELECT region_name FROM regions ORDER BY region_id")
    assert ok["allowed"] and ok["rows"][0] == ["North"]
