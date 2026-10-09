"""REST API: POST /ask for questions, POST /sql for guarded SQL, GET /schema."""

from __future__ import annotations

from functools import lru_cache

from fastapi import FastAPI

from . import __version__
from .assistant import FinanceAssistant
from .config import Settings
from .data_gen import ensure_db
from .models import Answer, AskRequest, SqlRequest
from .schema import ALLOWED_TABLES, GLOSSARY

app = FastAPI(title="Finance Analyst Assistant", version=__version__,
              description="Read-only, guarded natural-language questions over the finance database.")


@lru_cache(maxsize=1)
def get_assistant() -> FinanceAssistant:
    settings = Settings.from_env()
    ensure_db(settings.db_path)
    return FinanceAssistant(settings)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "backend": get_assistant().backend}


@app.get("/schema")
def schema() -> dict:
    return {"tables": ALLOWED_TABLES, "glossary": GLOSSARY}


@app.post("/ask", response_model=Answer)
def ask(req: AskRequest) -> Answer:
    return get_assistant().ask(req.question)


@app.post("/sql")
def sql(req: SqlRequest) -> dict:
    return get_assistant().run_sql(req.sql)
