"""LLM backends for the SQL planner: Anthropic (Claude) and any OpenAI-compatible API.

The LLM only ever writes SQL. It never sees query results and never writes the numbers in the
answer: results come straight from the database, so a model cannot hallucinate a figure.
"""

from __future__ import annotations

import json
import re
from typing import Protocol

from .config import Settings
from .schema import GLOSSARY, schema_text

# USD per million tokens (input, output), used only for the cost estimate in traces and reports.
PRICING = {"claude-haiku-4-5": (1.0, 5.0), "claude-sonnet-4-5": (3.0, 15.0), "gpt-4o-mini": (0.15, 0.6)}

SYSTEM_PROMPT = f"""You are the SQL planner for a finance team's read-only analytics assistant.
Write ONE SQLite SELECT query that answers the user's question over this schema:

{schema_text()}

{GLOSSARY}
Rules:
- Read-only: a single SELECT (CTEs allowed, no recursion). Never touch tables not listed above.
- Employee/HR data and customer contact details are not available. Never use SELECT * on customers.
- Return only the columns needed to answer: the label column(s) and the value(s), well named.
- For "top N" / "bottom N" questions, ORDER BY the value and LIMIT N.
- If the question cannot be answered from this schema (forecasts, data outside 2024-2025, people data),
  do not guess.

Reply with JSON only, no prose and no code fences:
{{"sql": "<the query>"}}  or  {{"cannot_answer": "<short reason>"}}
"""


class LLMClient(Protocol):
    name: str

    def complete(self, system: str, user: str) -> tuple[str, dict[str, int]]:
        """Return the model's text and token usage {"input_tokens": .., "output_tokens": ..}."""
        ...


class AnthropicClient:
    def __init__(self, model: str = "claude-haiku-4-5"):
        import anthropic  # optional dependency: pip install ".[anthropic]"

        self.client = anthropic.Anthropic()
        self.model = model
        self.name = f"anthropic:{model}"

    def complete(self, system: str, user: str) -> tuple[str, dict[str, int]]:
        msg = self.client.messages.create(
            model=self.model, max_tokens=1024, temperature=0, system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(block.text for block in msg.content if getattr(block, "type", "") == "text")
        return text, {"input_tokens": msg.usage.input_tokens, "output_tokens": msg.usage.output_tokens}


class OpenAICompatClient:
    """OpenAI, Azure OpenAI (via base URL) or a local model through Ollama."""

    def __init__(self, model: str = "gpt-4o-mini", base_url: str | None = None):
        import openai  # optional dependency: pip install ".[openai]"

        self.client = openai.OpenAI(base_url=base_url) if base_url else openai.OpenAI()
        self.model = model
        self.name = f"openai:{model}"

    def complete(self, system: str, user: str) -> tuple[str, dict[str, int]]:
        resp = self.client.chat.completions.create(
            model=self.model, temperature=0,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        usage = resp.usage
        return resp.choices[0].message.content or "", {
            "input_tokens": getattr(usage, "prompt_tokens", 0) or 0,
            "output_tokens": getattr(usage, "completion_tokens", 0) or 0,
        }


def build_client(settings: Settings) -> LLMClient | None:
    if settings.backend == "offline":
        return None
    if settings.backend == "anthropic":
        return AnthropicClient(settings.anthropic_model)
    if settings.backend == "openai":
        return OpenAICompatClient(settings.openai_model, settings.openai_base_url)
    raise ValueError(f"Unknown FINANCE_LLM backend '{settings.backend}' (use offline, anthropic or openai)")


def parse_reply(text: str) -> dict:
    """Extract the JSON object from a model reply (tolerates code fences and stray prose)."""
    text = re.sub(r"```(?:json)?", "", text).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("The model did not return JSON.")
    data = json.loads(match.group(0))
    if not isinstance(data, dict) or not ({"sql", "cannot_answer"} & data.keys()):
        raise ValueError("The model's JSON has neither 'sql' nor 'cannot_answer'.")
    return data


def estimate_cost(model_name: str, usage: dict[str, int]) -> float:
    model = model_name.split(":", 1)[-1]
    price_in, price_out = PRICING.get(model, (0.0, 0.0))
    return (usage.get("input_tokens", 0) * price_in + usage.get("output_tokens", 0) * price_out) / 1e6
