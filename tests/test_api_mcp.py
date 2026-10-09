import asyncio
import json
import os
import sys

from fastapi.testclient import TestClient
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from finance_analyst.api import app
from finance_analyst.config import PROJECT_ROOT


def test_api_ask_and_sql():
    client = TestClient(app)
    assert client.get("/health").json()["status"] == "ok"
    body = client.post("/ask", json={"question": "Revenue by region for 2025"}).json()
    assert body["status"] == "answered" and len(body["result"]["rows"]) == 4
    blocked = client.post("/sql", json={"sql": "DROP TABLE orders"}).json()
    assert blocked["allowed"] is False


def _text(result) -> dict:
    return json.loads(result.content[0].text)


def test_mcp_server_over_stdio(db_path):
    async def run():
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "finance_analyst.mcp_server"], cwd=str(PROJECT_ROOT),
            env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src"), "FINANCE_LLM": "offline"},
        )
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            names = {t.name for t in (await session.list_tools()).tools}
            assert {"ask_finance_question", "run_sql", "list_tables", "describe_table"} <= names
            question = {"question": "Top 3 customers by overdue balance"}
            ans = _text(await session.call_tool("ask_finance_question", question))
            assert ans["status"] == "answered" and len(ans["result"]["rows"]) == 3
            blocked = _text(await session.call_tool("run_sql", {"sql": "SELECT salary FROM employees"}))
            assert blocked["allowed"] is False and blocked["category"] == "sensitive_table"

    asyncio.run(run())
