"""Settings from environment variables, with a minimal ``.env`` loader (no extra dependency)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = PROJECT_ROOT / "data" / "finance.db"
QUESTIONS_DIR = PROJECT_ROOT / "data" / "questions"


def load_dotenv(path: str | Path | None = None) -> None:
    """Load KEY=VALUE lines from a .env file into os.environ without overriding real env vars."""
    path = Path(path) if path else Path.cwd() / ".env"
    if not path.is_file():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass
class Settings:
    backend: str = "offline"  # offline | anthropic | openai
    db_path: Path = DEFAULT_DB
    max_rows: int = 200
    timeout_ms: int = 3000
    anthropic_model: str = "claude-haiku-4-5"
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str | None = None
    trace_dir: Path | None = None
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()
        env = os.environ
        return cls(
            backend=env.get("FINANCE_LLM", "offline").strip().lower() or "offline",
            db_path=Path(env.get("FINANCE_DB_PATH", str(DEFAULT_DB))),
            max_rows=int(env.get("FINANCE_MAX_ROWS", "200")),
            timeout_ms=int(env.get("FINANCE_TIMEOUT_MS", "3000")),
            anthropic_model=env.get("ANTHROPIC_MODEL", "claude-haiku-4-5"),
            openai_model=env.get("OPENAI_MODEL", "gpt-4o-mini"),
            openai_base_url=env.get("OPENAI_BASE_URL") or None,
            trace_dir=Path(env["FINANCE_TRACE_DIR"]) if env.get("FINANCE_TRACE_DIR") else None,
        )
