"""Execution layers 2 and 3: a SQLite authorizer and a read-only connection with a time budget.

These work even if the validator is bypassed: SQLite itself refuses to read blocked tables or
columns, refuses every write, and aborts a query that runs past its time budget.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from .models import QueryResult
from .schema import BLOCKED_COLUMNS, BLOCKED_TABLES


class QueryError(RuntimeError):
    """Raised when SQLite refuses or aborts a query."""


_ALLOWED_ACTIONS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}
if hasattr(sqlite3, "SQLITE_RECURSIVE"):
    _ALLOWED_ACTIONS.add(sqlite3.SQLITE_RECURSIVE)
_BLOCKED_FUNCTIONS = {"load_extension", "readfile", "writefile", "fts3_tokenizer", "randomblob", "zeroblob"}


def _authorizer(action, arg1, arg2, _db, _trigger):
    if action not in _ALLOWED_ACTIONS:
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_READ:
        table = (arg1 or "").lower()
        if table in BLOCKED_TABLES or table.startswith("sqlite_"):
            return sqlite3.SQLITE_DENY
        if (table, (arg2 or "").lower()) in BLOCKED_COLUMNS:
            return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() in _BLOCKED_FUNCTIONS:
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def connect_readonly(db_path: str | Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}. Run: python scripts/generate_db.py")
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False)
    con.execute("PRAGMA query_only = ON")
    if hasattr(con, "setlimit"):
        con.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 10_000_000)  # no 1 GB blobs
        con.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
    con.set_authorizer(_authorizer)
    return con


def execute(con: sqlite3.Connection, sql: str, max_rows: int = 200, timeout_ms: int = 3000) -> QueryResult:
    """Run one query with a time budget; return at most ``max_rows`` rows (and say if more existed)."""
    deadline = time.perf_counter() + timeout_ms / 1000
    con.set_progress_handler(lambda: 1 if time.perf_counter() > deadline else 0, 10_000)
    start = time.perf_counter()
    try:
        cur = con.execute(sql)
        rows = cur.fetchmany(max_rows + 1)
    except sqlite3.OperationalError as err:
        if "interrupted" in str(err):
            raise QueryError(f"Query stopped: it ran longer than {timeout_ms} ms.") from err
        raise QueryError(f"SQLite refused the query: {err}") from err
    except (sqlite3.DatabaseError, sqlite3.Warning, sqlite3.ProgrammingError) as err:
        raise QueryError(f"SQLite refused the query: {err}") from err
    finally:
        con.set_progress_handler(None, 0)
    columns = [d[0] for d in (cur.description or [])]
    truncated = len(rows) > max_rows
    rows = rows[:max_rows]
    return QueryResult(
        columns=columns,
        rows=[list(r) for r in rows],
        row_count=len(rows),
        truncated=truncated,
        elapsed_ms=round((time.perf_counter() - start) * 1000, 2),
    )
