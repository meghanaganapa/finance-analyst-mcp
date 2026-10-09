"""Request policy: refuse HR/PII requests, write requests and prompt-injection attempts up front.

This runs before any planner (offline or LLM), so a refused request never reaches a model or the
database. The SQL validator and SQLite authorizer still apply afterwards in case something slips.
"""

from __future__ import annotations

import re

_RULES: list[tuple[str, re.Pattern[str], str]] = [
    ("hr_data", re.compile(r"\b(salar(y|ies)|payroll|wages?|employees?|staff|bank accounts?|highest paid)\b"),
     "Employee and payroll data is HR-restricted and not available through this assistant."),
    ("pii", re.compile(r"\b(e-?mails?|email addresses|phone numbers?|passwords?|home address(es)?)\b"),
     "Personal contact details are not available through this assistant."),
    ("write", re.compile(r"\b(delete|drop|truncate|insert|update|alter|remove|overwrite)\b|\bmark\b.*\bas\b"),
     "This assistant is read-only. Changes to finance data must go through the finance system."),
    ("injection", re.compile(r"ignore (all |your |the )?(previous |prior )?instructions|system override|admin mode"
                             r"|developer mode|jailbreak"),
     "Request refused: it tries to override the assistant's instructions."),
]


def check_request(question: str) -> tuple[str, str] | None:
    """Return ``(kind, reason)`` if the request must be refused, else ``None``."""
    text = question.lower()
    for kind, pattern, reason in _RULES:
        if pattern.search(text):
            return kind, reason
    return None
