"""SQL validator: the first of three safety layers (validator -> SQLite authorizer -> read-only connection).

The validator parses the SQL with sqlglot instead of matching keywords, so comments, casing and
quoting tricks don't get past it. It allows exactly one read-only SELECT over approved tables
and columns, with an allowlist of functions.
"""

from __future__ import annotations

import logging

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

from .models import GuardDecision
from .schema import ALLOWED_TABLES, BLOCKED_COLUMNS, BLOCKED_TABLES

logging.getLogger("sqlglot").setLevel(logging.ERROR)

# SQLite functions sqlglot does not model (they parse as Anonymous) that are safe for analytics.
SAFE_ANONYMOUS_FUNCTIONS = {
    "total", "julianday", "strftime", "date", "datetime", "time", "substr", "instr", "ifnull", "nullif",
    "iif", "round", "abs", "printf", "format", "trim", "ltrim", "rtrim", "lower", "upper", "length",
    "replace", "coalesce", "typeof", "sign", "unixepoch",
}
# Typed sqlglot functions that are unsafe or useless for analytics (resource abuse, side effects).
UNSAFE_TYPED_FUNCTIONS = {"Repeat", "Uuid", "Rand", "RandomBlob", "ZeroBlob"}

WRITE_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter, exp.Command, exp.Pragma,
    exp.Attach, exp.Detach, exp.Transaction, exp.Commit, exp.Rollback, exp.Merge, exp.TruncateTable,
    exp.Analyze,
)
SENSITIVE_COLUMN_NAMES = {col for _, col in BLOCKED_COLUMNS}


def _block(category: str, reason: str) -> GuardDecision:
    return GuardDecision(allowed=False, category=category, reason=reason)


def validate_sql(sql: str) -> GuardDecision:
    """Return whether ``sql`` may be executed, and why not if it may not."""
    if not sql or not sql.strip():
        return _block("empty", "No SQL was provided.")
    try:
        statements = [s for s in sqlglot.parse(sql, read="sqlite") if s is not None]
    except (ParseError, TokenError) as err:
        return _block("parse_error", f"SQL could not be parsed: {str(err).splitlines()[0][:120]}")
    if len(statements) != 1:
        return _block("multiple_statements", "Exactly one SQL statement is allowed.")
    stmt = statements[0]

    if not isinstance(stmt, (exp.Select, exp.SetOperation)):
        return _block("not_select", f"Only SELECT queries are allowed (got {type(stmt).__name__.upper()}).")
    for node in stmt.walk():
        if isinstance(node, WRITE_NODES):
            return _block("not_select", f"{type(node).__name__.upper()} is not allowed inside a query.")

    with_ = stmt.args.get("with") or stmt.args.get("with_")
    if with_ is not None and with_.args.get("recursive"):
        return _block("resource", "Recursive CTEs are not allowed (they can run forever).")

    cte_names = {cte.alias_or_name.lower() for cte in stmt.find_all(exp.CTE)}
    tables: set[str] = set()
    for table in stmt.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            name = table.this.name if isinstance(table.this, exp.Anonymous) else table.sql()
            return _block("dangerous_function", f"Table-valued function '{name}' is not allowed.")
        name = table.name.lower()
        db = (table.db or "").lower()
        if db and db != "main":
            return _block("unknown_table", f"Schema '{db}' is not allowed.")
        if name in cte_names and not db:
            continue
        if name.startswith("sqlite_"):
            return _block("system_table", f"System table '{name}' is not allowed.")
        if name in BLOCKED_TABLES:
            return _block("sensitive_table", f"Table '{name}' contains HR data and is not available.")
        if name not in ALLOWED_TABLES:
            return _block("unknown_table", f"Unknown table '{name}'.")
        tables.add(name)

    for func in stmt.find_all(exp.Func):
        if isinstance(func, exp.Anonymous):
            fname = func.name.lower()
            if fname not in SAFE_ANONYMOUS_FUNCTIONS:
                return _block("dangerous_function", f"Function '{fname}' is not allowed.")
        elif type(func).__name__ in UNSAFE_TYPED_FUNCTIONS:
            return _block("dangerous_function", f"Function '{type(func).__name__}' is not allowed.")

    for col in stmt.find_all(exp.Column):
        if col.name.lower() in SENSITIVE_COLUMN_NAMES:
            return _block("sensitive_column", f"Column '{col.name}' contains personal data and is not available.")

    tables_with_blocked_cols = {t for t, _ in BLOCKED_COLUMNS}
    if tables & tables_with_blocked_cols and any(True for _ in stmt.find_all(exp.Star)):
        return _block(
            "sensitive_column",
            "SELECT * is not allowed on tables with personal data; list the columns you need.",
        )

    return GuardDecision(allowed=True, category="ok", reason="Read-only SELECT over approved tables.",
                         tables=sorted(tables))
