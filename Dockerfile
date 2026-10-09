FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY scripts ./scripts
COPY data/questions ./data/questions
RUN pip install --no-cache-dir ".[anthropic,openai]" && python scripts/generate_db.py

ENV FINANCE_LLM=offline \
    FINANCE_DB_PATH=/app/data/finance.db
EXPOSE 8000
# REST API by default; for MCP over stdio: docker run -i <image> python -m finance_analyst.mcp_server
CMD ["uvicorn", "finance_analyst.api:app", "--host", "0.0.0.0", "--port", "8000"]
