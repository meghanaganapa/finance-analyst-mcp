# LinkedIn post draft

> Edit this into your own voice before posting. Add an image: the architecture diagram, the CLI output, or the results table. Every number below matches `reports/`.

---

My finance assistant scored 100%. On new wording, it scored 35.9%.

I built an MCP server that lets a finance team ask questions of a sales and finance SQL database in plain English: "Top 10 customers last quarter?", "Revenue vs budget by region?", "Who owes us the most?" It plugs into Claude Desktop, Claude Code, Cursor or VS Code as tools.

The no-LLM version maps questions to governed metrics, and it answered every question I built it on correctly. Then I tested it the honest way: the same 14 business questions, but phrased in ways it had never seen. Accuracy fell to 35.9%, and to 16% on 25 messy hand-written questions.

But here's the part I'm proud of: on new wording it auto-answered 11 questions and got all 11 right. Everything else was flagged for a human or declined. 0 of 41 misses were silent. In finance, "please check this" beats a confident wrong number.

How it works:
🔹 Policy agent refuses salary, email, delete and prompt-injection requests before anything runs
🔹 Planner: Claude, any OpenAI-compatible model, or a free offline semantic layer
🔹 3 safety layers that don't trust each other: a SQL parser (not keyword matching), SQLite's own authorizer, and a read-only connection with time and row limits
🔹 The LLM only writes SQL. Numbers come straight from the database, so it can't invent a figure
🔹 LLM SQL is cross-checked against the governed metric definitions. If they disagree, a human reviews it
🔹 Every question gets a full trace

Safety results:
✅ 48/48 attack queries stopped (writes, stacked statements, 8 ways of reaching the HR table, PII columns, runaway joins)
✅ 47/48 caught by the validator alone; the SQLite layers caught the last one
✅ 0/153 legitimate queries wrongly blocked
✅ 12/12 out-of-scope requests refused or declined

The lesson: a random test split would have shown me 100% and I'd have believed it. Holding out whole phrasings is what showed me the gap, and that gap is exactly what an LLM planner is for.

Code, evaluation and design decisions: https://github.com/meghanaganapa/finance-analyst-mcp

If you've put an LLM in front of a database: what stops it from running the wrong query?

#AIAgents #MCP #LLM #DataEngineering #SQL #FinanceAnalytics #GenAI #Python
