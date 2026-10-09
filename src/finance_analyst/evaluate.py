"""Evaluation: answer accuracy (execution match vs hand-written gold SQL) and safety.

    python -m finance_analyst.evaluate --split all            # offline, writes reports/*.json
    python -m finance_analyst.evaluate --split hard --backend anthropic

Splits: dev (used while building the offline planner), heldout (paraphrase templates never seen
during development), hard (hand-written). Held-out, hard and safety sets are checksum-locked.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

from .assistant import FinanceAssistant
from .compare import results_match
from .config import PROJECT_ROOT, QUESTIONS_DIR, Settings
from .data_gen import generate
from .executor import QueryError, connect_readonly, execute
from .guard import validate_sql

REPORTS = PROJECT_ROOT / "reports"
SPLITS = ("dev", "heldout", "hard")


def load_jsonl(name: str) -> list[dict]:
    with open(QUESTIONS_DIR / name) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def verify_locked() -> list[str]:
    """Return the locked files whose checksum no longer matches LOCKED.sha256."""
    bad = []
    for line in (QUESTIONS_DIR / "LOCKED.sha256").read_text().splitlines():
        digest, name = line.split()
        if hashlib.sha256((QUESTIONS_DIR / name).read_bytes()).hexdigest() != digest:
            bad.append(name)
    return bad


def bootstrap_ci(values: list[int], n_boot: int = 2000, seed: int = 0) -> list[float]:
    if not values:
        return [0.0, 0.0]
    rng = random.Random(seed)
    n = len(values)
    stats = sorted(sum(rng.choice(values) for _ in range(n)) / n for _ in range(n_boot))
    return [round(stats[int(0.025 * n_boot)], 3), round(stats[int(0.975 * n_boot) - 1], 3)]


def _rate(values: list[int]) -> dict:
    return {"value": round(sum(values) / len(values), 3) if values else 0.0, "ci95": bootstrap_ci(values),
            "n": len(values)}


def evaluate_split(assistant: FinanceAssistant, split: str, limit: int | None = None) -> dict:
    questions = load_jsonl(f"{split}.jsonl")[:limit]
    gold_con = connect_readonly(assistant.settings.db_path)
    rows, by_family = [], defaultdict(list)
    usage_in = usage_out = 0
    usd = 0.0
    for q in questions:
        gold = execute(gold_con, q["gold_sql"], max_rows=10_000).rows
        ans = assistant.ask(q["question"])
        answered = ans.status in ("answered", "needs_review")
        correct = bool(answered and ans.result is not None and results_match(gold, ans.result.rows, q["ordered"]))
        usage_in += int(ans.llm_usage.get("input_tokens", 0))
        usage_out += int(ans.llm_usage.get("output_tokens", 0))
        usd += float(ans.llm_usage.get("usd", 0.0))
        rows.append({"id": q["id"], "question": q["question"], "status": ans.status, "correct": correct,
                     "sql": ans.sql, "review_reasons": ans.review_reasons})
        by_family[q["family"]].append(correct)

    n = len(rows)
    correct = [int(r["correct"]) for r in rows]
    auto = [r for r in rows if r["status"] == "answered"]
    not_correct = [r for r in rows if not r["correct"]]
    report = {
        "backend": assistant.backend,
        "split": split,
        "n": n,
        "execution_accuracy": _rate(correct),
        "answered_rate": round(sum(r["status"] in ("answered", "needs_review") for r in rows) / n, 3),
        "auto_answer_rate": round(len(auto) / n, 3),
        "auto_answer_accuracy": _rate([int(r["correct"]) for r in auto]),
        "flagged_for_review_rate": round(sum(r["status"] == "needs_review" for r in rows) / n, 3),
        "abstain_rate": round(sum(r["status"] == "abstained" for r in rows) / n, 3),
        "silent_error_rate": round(sum(r["status"] == "answered" and not r["correct"] for r in rows) / n, 3),
        "misses_caught_by_review": round(
            sum(r["status"] != "answered" for r in not_correct) / len(not_correct), 3) if not_correct else 1.0,
        "accuracy_by_family": {k: round(sum(v) / len(v), 3) for k, v in sorted(by_family.items())},
        "llm_tokens": {"input": usage_in, "output": usage_out},
        "llm_cost_usd_total": round(usd, 4),
        "llm_cost_usd_per_question": round(usd / n, 5) if n else 0.0,
        "details": rows,
    }
    return report


def evaluate_safety(assistant: FinanceAssistant) -> dict:
    """Unsafe SQL through each layer separately and together; false blocks on gold SQL; NL refusals."""
    unsafe = load_jsonl("unsafe_sql.jsonl")
    engine = connect_readonly(assistant.settings.db_path)
    per_attack, details = defaultdict(lambda: [0, 0]), []
    validator_blocked = engine_stopped = combined = 0
    for item in unsafe:
        decision = validate_sql(item["sql"])
        try:  # engine layers alone: validator bypassed on purpose
            execute(engine, item["sql"], max_rows=50, timeout_ms=1000)
            engine_outcome = "executed"
        except QueryError as err:
            msg = str(err)
            if "not authorized" in msg or "access to" in msg or "authorization denied" in msg:
                engine_outcome = "refused_by_authorizer"
            elif "one statement" in msg:
                engine_outcome = "refused_by_driver"  # sqlite3 runs one statement per call
            elif "longer than" in msg:
                engine_outcome = "timeout"
            else:
                engine_outcome = "sql_error"  # failed, but not because of a safety control
        is_noop = not item["sql"].strip()
        stopped_by_engine = engine_outcome in ("refused_by_authorizer", "timeout", "refused_by_driver") or is_noop
        validator_blocked += not decision.allowed
        engine_stopped += stopped_by_engine
        combined += (not decision.allowed) or stopped_by_engine
        per_attack[item["attack"]][0] += not decision.allowed
        per_attack[item["attack"]][1] += 1
        details.append({"id": item["id"], "attack": item["attack"], "validator": decision.category,
                        "engine_only": "no-op (empty)" if is_noop else engine_outcome})

    gold_sql = [q["gold_sql"] for split in SPLITS for q in load_jsonl(f"{split}.jsonl")]
    false_blocks = sum(not validate_sql(sql).allowed for sql in gold_sql)

    oos = load_jsonl("out_of_scope.jsonl")
    oos_rows = []
    for item in oos:
        ans = assistant.ask(item["question"])
        oos_rows.append({"id": item["id"], "kind": item["kind"], "status": ans.status,
                         "ok": ans.status in ("refused", "abstained")})

    n = len(unsafe)
    return {
        "backend": assistant.backend,
        "unsafe_sql": {
            "n": n,
            "blocked_by_validator": validator_blocked,
            "stopped_by_engine_alone": engine_stopped,
            "stopped_by_both_layers": combined,
            "blocked_rate_validator": round(validator_blocked / n, 3),
            "blocked_rate_engine_alone": round(engine_stopped / n, 3),
            "blocked_rate_combined": round(combined / n, 3),
            "validator_by_attack": {k: f"{v[0]}/{v[1]}" for k, v in sorted(per_attack.items())},
            "details": details,
        },
        "safe_sql_false_block": {"n": len(gold_sql), "blocked": false_blocks,
                                 "rate": round(false_blocks / len(gold_sql), 3)},
        "out_of_scope_requests": {"n": len(oos_rows), "refused_or_abstained": sum(r["ok"] for r in oos_rows),
                                  "details": oos_rows},
    }


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def summary_markdown(reports: list[dict], safety: dict | None) -> str:
    out = ["### Answer accuracy (execution match vs hand-written gold SQL)", "",
           "| Split | n | Accuracy (95% CI) | Auto-answered | Accuracy when auto-answered | Flagged | Abstained |"
           " Silent errors |", "|---|---|---|---|---|---|---|---|"]
    for r in reports:
        acc = r["execution_accuracy"]
        out.append(
            f"| {r['split']} | {r['n']} | {_pct(acc['value'])} ({_pct(acc['ci95'][0])}–{_pct(acc['ci95'][1])}) "
            f"| {_pct(r['auto_answer_rate'])} | {_pct(r['auto_answer_accuracy']['value'])} "
            f"| {_pct(r['flagged_for_review_rate'])} | {_pct(r['abstain_rate'])} | {_pct(r['silent_error_rate'])} |")
    if safety:
        u = safety["unsafe_sql"]
        out += ["", "### Safety", "",
                f"- Unsafe SQL blocked by the validator: **{u['blocked_by_validator']}/{u['n']}** "
                f"({_pct(u['blocked_rate_validator'])})",
                f"- Stopped by the SQLite layers alone (validator bypassed): {u['stopped_by_engine_alone']}/{u['n']}",
                f"- Stopped by validator + SQLite together: **{u['stopped_by_both_layers']}/{u['n']}**",
                f"- Safe gold queries wrongly blocked: {safety['safe_sql_false_block']['blocked']}/"
                f"{safety['safe_sql_false_block']['n']}",
                f"- Out-of-scope requests refused or abstained: "
                f"{safety['out_of_scope_requests']['refused_or_abstained']}/{safety['out_of_scope_requests']['n']}"]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", default="all", choices=[*SPLITS, "all"])
    ap.add_argument("--backend", default=None, help="offline | anthropic | openai (default: FINANCE_LLM)")
    ap.add_argument("--limit", type=int, default=None, help="evaluate only the first N questions per split")
    ap.add_argument("--no-safety", action="store_true")
    ap.add_argument("--no-write", action="store_true", help="print only; don't write reports/")
    args = ap.parse_args(argv)

    stale = verify_locked()
    if stale:
        print(f"Locked evaluation files changed: {stale}. Refusing to evaluate.", file=sys.stderr)
        return 2

    settings = Settings.from_env()
    if args.backend:
        settings.backend = args.backend
    if not Path(settings.db_path).exists():
        generate(settings.db_path)
    assistant = FinanceAssistant(settings)

    splits = SPLITS if args.split == "all" else (args.split,)
    reports = [evaluate_split(assistant, s, args.limit) for s in splits]
    safety = None if args.no_safety else evaluate_safety(assistant)

    if not args.no_write:
        REPORTS.mkdir(exist_ok=True)
        tag = settings.backend
        for r in reports:
            (REPORTS / f"eval_{tag}_{r['split']}.json").write_text(json.dumps(r, indent=2) + "\n")
        if safety:
            (REPORTS / f"safety_{tag}.json").write_text(json.dumps(safety, indent=2) + "\n")
    print(summary_markdown(reports, safety))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
