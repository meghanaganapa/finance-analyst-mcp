"""Pydantic models shared by the CLI, API, MCP server and evaluation."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Status = Literal["answered", "needs_review", "refused", "abstained", "error"]


class GuardDecision(BaseModel):
    allowed: bool
    category: str
    reason: str
    tables: list[str] = Field(default_factory=list)


class QueryResult(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool = False
    elapsed_ms: float = 0.0


class TraceStep(BaseModel):
    step: str
    detail: str = ""
    ms: float = 0.0
    data: dict[str, Any] = Field(default_factory=dict)


class Answer(BaseModel):
    question: str
    status: Status
    answer: str
    sql: str | None = None
    result: QueryResult | None = None
    backend: str = "offline"
    review_reasons: list[str] = Field(default_factory=list)
    trace: list[TraceStep] = Field(default_factory=list)
    llm_usage: dict[str, float] = Field(default_factory=dict)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class SqlRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=5000)
