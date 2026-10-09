import json

import pytest

from finance_analyst.config import QUESTIONS_DIR
from finance_analyst.guard import validate_sql


def test_allows_simple_select():
    d = validate_sql("SELECT region_name FROM regions")
    assert d.allowed and d.tables == ["regions"]


@pytest.mark.parametrize("sql", [
    "DROP TABLE invoices",
    "DELETE FROM orders",
    "UPDATE invoices SET status = 'paid'",
    "INSERT INTO regions VALUES (9, 'X')",
    "REPLACE INTO regions VALUES (1, 'X')",
    "PRAGMA writable_schema = ON",
    "ATTACH DATABASE '/tmp/x.db' AS x",
    "VACUUM INTO '/tmp/x.db'",
])
def test_blocks_writes_and_admin(sql):
    assert not validate_sql(sql).allowed


def test_blocks_stacked_statements_even_behind_comments():
    d = validate_sql("SELECT region_name FROM regions /* ; */ ; DROP TABLE regions --")
    assert not d.allowed and d.category == "multiple_statements"


@pytest.mark.parametrize("sql", [
    "SELECT * FROM employees",
    'SELECT * FROM "EMPLOYEES"',
    "SELECT * FROM main.employees",
    "WITH e AS (SELECT * FROM employees) SELECT * FROM e",
    "SELECT region_name FROM regions UNION SELECT bank_account FROM employees",
])
def test_blocks_hr_table_in_any_disguise(sql):
    d = validate_sql(sql)
    assert not d.allowed and d.category == "sensitive_table"


def test_blocks_pii_column_and_star_on_customers():
    assert validate_sql("SELECT contact_email FROM customers").category == "sensitive_column"
    assert validate_sql("SELECT c.* FROM customers c").category == "sensitive_column"
    assert validate_sql("SELECT * FROM regions").allowed  # star is fine without personal data


@pytest.mark.parametrize("sql", [
    "SELECT load_extension('/tmp/evil.so')",
    "SELECT length(randomblob(1000000000))",
    "SELECT * FROM pragma_table_info('employees')",
    "SELECT sql FROM sqlite_master",
])
def test_blocks_dangerous_functions_and_system_tables(sql):
    assert not validate_sql(sql).allowed


def test_blocks_recursive_cte():
    sql = "WITH RECURSIVE r(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM r) SELECT COUNT(*) FROM r"
    assert validate_sql(sql).category == "resource"


def test_no_gold_query_is_falsely_blocked():
    for split in ("dev", "heldout", "hard"):
        for line in (QUESTIONS_DIR / f"{split}.jsonl").read_text().splitlines():
            q = json.loads(line)
            assert validate_sql(q["gold_sql"]).allowed, q["id"]
