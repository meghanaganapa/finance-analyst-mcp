import pytest

from finance_analyst.executor import QueryError, connect_readonly, execute


@pytest.fixture(scope="module")
def con(db_path):
    return connect_readonly(db_path)


def test_authorizer_blocks_hr_table_without_the_validator(con):
    with pytest.raises(QueryError, match="employees"):
        execute(con, "SELECT salary FROM employees")


def test_authorizer_blocks_pii_column_without_the_validator(con):
    with pytest.raises(QueryError):
        execute(con, "SELECT * FROM customers")


def test_connection_is_read_only(con):
    with pytest.raises(QueryError):
        execute(con, "DELETE FROM orders")


def test_time_budget_stops_runaway_queries(con):
    with pytest.raises(QueryError, match="longer than"):
        execute(con, "SELECT COUNT(*) FROM order_lines a, order_lines b, order_lines c", timeout_ms=300)


def test_row_limit_truncates_and_says_so(con):
    res = execute(con, "SELECT order_id FROM orders", max_rows=10)
    assert res.row_count == 10 and res.truncated
