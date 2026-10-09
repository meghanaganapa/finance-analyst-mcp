"""Command line: ask questions, run guarded SQL, inspect the schema.

    finance-analyst ask "Top 5 customers by revenue in Q3 2025"
    finance-analyst ask "Revenue vs budget by region for 2025" --trace
    finance-analyst sql "SELECT region_name FROM regions"
    finance-analyst schema
"""

from __future__ import annotations

import argparse
import json
import sys

from .assistant import FinanceAssistant
from .config import Settings
from .data_gen import ensure_db
from .schema import GLOSSARY, schema_text


def _assistant(backend: str | None) -> FinanceAssistant:
    settings = Settings.from_env()
    if backend:
        settings.backend = backend
    ensure_db(settings.db_path)
    return FinanceAssistant(settings)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="finance-analyst", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_ask = sub.add_parser("ask", help="ask a finance question in plain English")
    p_ask.add_argument("question")
    p_ask.add_argument("--backend", help="offline | anthropic | openai (default: FINANCE_LLM)")
    p_ask.add_argument("--trace", action="store_true", help="print the per-step trace")
    p_ask.add_argument("--json", action="store_true", help="print the full answer as JSON")
    p_sql = sub.add_parser("sql", help="run a read-only SQL query through the guard")
    p_sql.add_argument("query")
    sub.add_parser("schema", help="print the tables and business definitions the assistant can use")
    args = ap.parse_args(argv)

    if args.cmd == "schema":
        print(schema_text())
        print()
        print(GLOSSARY)
        return 0
    if args.cmd == "sql":
        out = _assistant(None).run_sql(args.query)
        print(json.dumps(out, indent=2, default=str))
        return 0 if out["allowed"] else 1

    ans = _assistant(args.backend).ask(args.question)
    if args.json:
        print(ans.model_dump_json(indent=2))
        return 0
    print(f"Q: {ans.question}")
    print(f"Status: {ans.status}   Backend: {ans.backend}")
    if ans.sql:
        print(f"SQL: {ans.sql}")
    print()
    print(ans.answer)
    for reason in ans.review_reasons:
        print(f"⚠ Review: {reason}")
    if args.trace:
        print("\nTrace:")
        for step in ans.trace:
            print(f"  {step.step:<18} {step.ms:>8.2f} ms  {step.detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
