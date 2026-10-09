.PHONY: install data questions test lint eval eval-claude eval-openai demo api mcp

install:
	pip install -e ".[dev,anthropic,openai]"

data:
	python scripts/generate_db.py

# Rebuilding question files breaks the LOCKED.sha256 check on purpose.
questions:
	python scripts/build_questions.py && python scripts/build_hard_set.py && python scripts/build_safety_sets.py

test:
	pytest -q

lint:
	ruff check src tests scripts

eval:
	python -m finance_analyst.evaluate --split all

# Claude on the hard set + 20 held-out questions (needs ANTHROPIC_API_KEY; well under $0.10 with Haiku 4.5)
eval-claude:
	python -m finance_analyst.evaluate --backend anthropic --split hard
	python -m finance_analyst.evaluate --backend anthropic --split heldout --limit 20 --no-safety

eval-openai:
	python -m finance_analyst.evaluate --backend openai --split hard

demo:
	finance-analyst ask "Revenue vs budget by region for 2025" --trace

api:
	uvicorn finance_analyst.api:app --reload

mcp:
	python -m finance_analyst.mcp_server
