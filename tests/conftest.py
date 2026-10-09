import pytest

from finance_analyst.assistant import FinanceAssistant
from finance_analyst.config import DEFAULT_DB, Settings
from finance_analyst.data_gen import ensure_db


@pytest.fixture(scope="session")
def db_path():
    return ensure_db(DEFAULT_DB)


@pytest.fixture(scope="session")
def assistant(db_path):
    return FinanceAssistant(Settings(backend="offline", db_path=db_path), llm=None)


class FakeLLM:
    """Scripted LLM: returns the queued replies in order (or raises if a reply is an Exception)."""

    name = "fake:test"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def complete(self, system, user):
        self.prompts.append(user)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply, {"input_tokens": 100, "output_tokens": 20}


@pytest.fixture
def make_llm_assistant(db_path):
    def _make(*replies):
        llm = FakeLLM(*replies)
        return FinanceAssistant(Settings(backend="fake", db_path=db_path), llm=llm), llm

    return _make
