"""MCP server: lets Claude Desktop, Claude Code, Cursor or VS Code use the finance database safely.

Run:  python -m finance_analyst.mcp_server   (stdio transport)

Tools: list_tables, describe_table, business_glossary, run_sql (guarded), ask_finance_question.
Every tool is read-only; run_sql goes through the validator, the SQLite authorizer, a read-only
connection, a time budget and a row limit.
"""

from __future__ import annotations

from functools import lru_cache

from mcp.server.mcpserver import MCPServer

from .assistant import FinanceAssistant
from .config import Settings
from .data_gen import ensure_db
from .schema import ALLOWED_TABLES, GLOSSARY

server = MCPServer(
    name="finance-analyst",
    instructions=(
        "Read-only access to Harbourline Supplies' sales and finance database (2024-2025). "
        "Prefer ask_finance_question for business questions; use run_sql for custom read-only queries. "
        "HR data and customer contact details are not available."
    ),
)


@lru_cache(maxsize=1)
def _assistant() -> FinanceAssistant:
    settings = Settings.from_env()
    ensure_db(settings.db_path)
    return FinanceAssistant(settings)


@server.tool()
def list_tables() -> list[str]:
    """List the tables available for analysis."""
    return list(ALLOWED_TABLES)


@server.tool()
def describe_table(table: str) -> dict:
    """Describe one table's columns (name -> meaning)."""
    cols = ALLOWED_TABLES.get(table.lower())
    if cols is None:
        return {"error": f"Unknown or restricted table '{table}'. Available: {', '.join(ALLOWED_TABLES)}"}
    return {"table": table.lower(), "columns": cols}


@server.tool()
def business_glossary() -> str:
    """How revenue, margin, AOV, overdue and other metrics are defined. Read this before writing SQL."""
    return GLOSSARY


@server.tool()
def run_sql(sql: str) -> dict:
    """Run ONE read-only SQLite SELECT. Unsafe or restricted queries are blocked with a reason.
    At most 200 rows are returned ('truncated' says if there were more)."""
    return _assistant().run_sql(sql)


@server.tool()
def ask_finance_question(question: str) -> dict:
    """Answer a finance question in plain English (e.g. 'Top 5 customers by revenue in Q3 2025').
    Returns the answer, the SQL used, the rows, a status (answered / needs_review / refused /
    abstained) and any reasons a human should check the answer."""
    ans = _assistant().ask(question)
    return ans.model_dump(exclude={"trace"})


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
