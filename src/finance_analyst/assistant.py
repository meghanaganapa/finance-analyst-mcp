"""The finance assistant: policy -> planner -> SQL guard -> executor -> reviewer -> answer.

Each step is a small agent with one job, and every step is recorded in a per-question trace.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from . import semantic
from .compare import results_match
from .config import Settings
from .executor import QueryError, connect_readonly, execute
from .guard import validate_sql
from .llm import SYSTEM_PROMPT, LLMClient, build_client, estimate_cost, parse_reply
from .models import Answer, QueryResult, TraceStep
from .policy import check_request


class _Trace:
    def __init__(self) -> None:
        self.steps: list[TraceStep] = []

    @contextmanager
    def step(self, name: str):
        rec = TraceStep(step=name)
        start = time.perf_counter()
        try:
            yield rec
        finally:
            rec.ms = round((time.perf_counter() - start) * 1000, 2)
            self.steps.append(rec)


def format_value(v) -> str:
    if isinstance(v, float):
        return f"{v:,.2f}"
    if isinstance(v, int):
        return f"{v:,}"
    return "—" if v is None else str(v)


def render_answer(result: QueryResult, max_rows: int = 12) -> str:
    if result.row_count == 0:
        return "The query returned no rows."
    if result.row_count == 1 and len(result.columns) == 1:
        return f"{result.columns[0]}: {format_value(result.rows[0][0])}"
    header = "| " + " | ".join(result.columns) + " |"
    sep = "|" + "|".join("---" for _ in result.columns) + "|"
    body = ["| " + " | ".join(format_value(v) for v in row) + " |" for row in result.rows[:max_rows]]
    more = f"\n…and {result.row_count - max_rows} more rows" if result.row_count > max_rows else ""
    return "\n".join([header, sep, *body]) + more


class FinanceAssistant:
    def __init__(self, settings: Settings | None = None, llm: LLMClient | None = None,
                 con: sqlite3.Connection | None = None):
        self.settings = settings or Settings.from_env()
        self.llm = llm if llm is not None else build_client(self.settings)
        self.con = con or connect_readonly(self.settings.db_path)

    @property
    def backend(self) -> str:
        return self.llm.name if self.llm else "offline"

    # ------------------------------------------------------------------ raw SQL tool
    def run_sql(self, sql: str) -> dict:
        decision = validate_sql(sql)
        if not decision.allowed:
            return {"allowed": False, "category": decision.category, "reason": decision.reason}
        try:
            result = execute(self.con, sql, self.settings.max_rows, self.settings.timeout_ms)
        except QueryError as err:
            return {"allowed": False, "category": "engine", "reason": str(err)}
        return {"allowed": True, **result.model_dump()}

    # ------------------------------------------------------------------ question answering
    def ask(self, question: str) -> Answer:
        trace = _Trace()
        answer = self._ask(question, trace)
        answer.trace = trace.steps
        if self.settings.trace_dir:
            self._write_trace(answer)
        return answer

    def _ask(self, question: str, trace: _Trace) -> Answer:
        base = {"question": question, "backend": self.backend}

        with trace.step("policy") as s:
            refusal = check_request(question)
            s.detail = f"refused ({refusal[0]})" if refusal else "ok"
        if refusal:
            return Answer(**base, status="refused", answer=refusal[1])

        review: list[str] = []
        usage = {"input_tokens": 0, "output_tokens": 0}
        offline_plan = semantic.parse(question)

        if self.llm is None:
            with trace.step("planner:offline") as s:
                s.detail = offline_plan.abstain_reason or f"metric={offline_plan.metric}, dim={offline_plan.dimension}"
            if offline_plan.abstain_reason:
                return Answer(**base, status="abstained", answer=offline_plan.abstain_reason)
            if offline_plan.unknown_words:
                review.append(f"Parts of the question were not understood: {', '.join(offline_plan.unknown_words)}")
            sql = offline_plan.sql
        else:
            sql, abstain = self._llm_plan(question, trace, usage, feedback=None)
            if abstain is not None:
                return Answer(**base, status="abstained", answer=abstain, llm_usage=usage)
            if sql is None:  # LLM failed: fall back to the offline planner
                if offline_plan.abstain_reason:
                    return Answer(**base, status="abstained", answer=offline_plan.abstain_reason, llm_usage=usage)
                sql = offline_plan.sql
                review.append("The LLM planner failed; this answer comes from the offline semantic layer.")
                if offline_plan.unknown_words:
                    review.append(f"Parts of the question were not understood: {', '.join(offline_plan.unknown_words)}")

        result, sql, error = self._guard_and_run(question, sql, trace, usage)
        if result is None:
            return Answer(**base, status="error", answer=error or "The query failed.", sql=sql, llm_usage=usage)

        with trace.step("reviewer") as s:
            if result.row_count == 0:
                review.append("The query returned no rows.")
            if result.truncated:
                review.append(f"Only the first {self.settings.max_rows} rows are shown.")
            if result.row_count and all(v is None for row in result.rows for v in row):
                review.append("The query returned only empty values.")
            if self.llm is not None and not offline_plan.abstain_reason and not offline_plan.unknown_words \
                    and sql != offline_plan.sql:
                try:
                    check = execute(self.con, offline_plan.sql, self.settings.max_rows, self.settings.timeout_ms)
                    if not results_match(check.rows, result.rows, ordered=False):
                        review.append("The governed semantic layer computes a different result for this question.")
                except QueryError:
                    pass
            s.detail = "; ".join(review) or "no issues"

        if self.llm is not None:
            usage["usd"] = round(estimate_cost(self.llm.name, usage), 6)
        return Answer(**base, status="needs_review" if review else "answered", answer=render_answer(result),
                      sql=sql, result=result, review_reasons=review, llm_usage=usage)

    def _llm_plan(self, question: str, trace: _Trace, usage: dict, feedback: str | None):
        """Return (sql, abstain_reason). (None, None) means the LLM failed and we should fall back."""
        prompt = question if feedback is None else (
            f"{question}\n\nYour previous SQL was rejected:\n{feedback}\nReturn a corrected query.")
        with trace.step("planner:llm" if feedback is None else "planner:llm_repair") as s:
            try:
                text, u = self.llm.complete(SYSTEM_PROMPT, prompt)
                for k in ("input_tokens", "output_tokens"):
                    usage[k] = usage.get(k, 0) + int(u.get(k, 0))
                data = parse_reply(text)
            except Exception as err:  # network, auth, bad JSON: never take the service down
                s.detail = f"LLM failed: {type(err).__name__}: {str(err)[:120]}"
                return None, None
            if "cannot_answer" in data and not data.get("sql"):
                s.detail = f"cannot answer: {data['cannot_answer']}"
                return None, f"I can't answer that from the finance data: {data['cannot_answer']}"
            s.detail = "sql generated"
            s.data = {"sql": data["sql"]}
            return str(data["sql"]).strip().rstrip(";"), None

    def _guard_and_run(self, question: str, sql: str, trace: _Trace, usage: dict):
        """Validate and execute, with one LLM repair round. Returns (result, sql, error)."""
        attempts = 2 if self.llm is not None else 1
        error = None
        for attempt in range(attempts):
            with trace.step("guard") as s:
                decision = validate_sql(sql)
                s.detail = f"{decision.category}: {decision.reason}"
                s.data = {"sql": sql}
            if decision.allowed:
                with trace.step("executor") as s:
                    try:
                        result = execute(self.con, sql, self.settings.max_rows, self.settings.timeout_ms)
                        s.detail = f"{result.row_count} rows in {result.elapsed_ms} ms"
                        return result, sql, None
                    except QueryError as err:
                        error = str(err)
                        s.detail = error
            else:
                error = f"Query blocked by the SQL guard ({decision.category}): {decision.reason}"
            if attempt + 1 < attempts:
                new_sql, abstain = self._llm_plan(question, trace, usage, feedback=f"{sql}\nError: {error}")
                if new_sql is None:
                    break
                sql = new_sql
        return None, sql, error

    def _write_trace(self, answer: Answer) -> None:
        directory = Path(self.settings.trace_dir)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}.json"
        path.write_text(json.dumps(answer.model_dump(), indent=2, default=str))
