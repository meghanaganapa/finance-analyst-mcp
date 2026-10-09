"""Execution-match comparison: does the assistant's result contain the gold result?

Column names and extra columns are ignored (an answer that adds a helpful column is still right),
but every gold column must appear with the same values, row for row. Ordered questions (top-N,
month-by-month) must also match the gold row order. Numbers match within a small tolerance, so
ROUND(x, 2) vs an unrounded value is not a false failure.
"""

from __future__ import annotations

import itertools
import math
from collections import Counter
from typing import Any


def _norm(v: Any) -> Any:
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return v.strip().lower()
    return v


def _eq(a: Any, b: Any) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        return math.isclose(a, b, rel_tol=1e-4, abs_tol=0.051)
    return a == b


def _key(v: Any) -> tuple:
    if isinstance(v, float):
        return (0, round(v, 1), "")
    if v is None:
        return (1, 0.0, "")
    return (2, 0.0, str(v))


def _rows_equal(gold: list[tuple], pred: list[tuple], ordered: bool) -> bool:
    if len(gold) != len(pred):
        return False
    if not ordered:
        gold = sorted(gold, key=lambda r: tuple(_key(v) for v in r))
        pred = sorted(pred, key=lambda r: tuple(_key(v) for v in r))
    return all(all(_eq(a, b) for a, b in zip(g, p, strict=True)) for g, p in zip(gold, pred, strict=True))


def results_match(gold_rows: list, pred_rows: list, ordered: bool = False) -> bool:
    gold = [tuple(_norm(v) for v in r) for r in gold_rows]
    pred = [tuple(_norm(v) for v in r) for r in pred_rows]
    if len(gold) != len(pred):
        return False
    if not gold:
        return True
    n_gold, n_pred = len(gold[0]), len(pred[0])
    if n_pred < n_gold:
        return False
    # Candidate predicted columns for each gold column: same multiset of (rounded) values.
    def sig(rows: list[tuple], j: int) -> Counter:
        return Counter(_key(r[j]) for r in rows)

    candidates = []
    for j in range(n_gold):
        g = sig(gold, j)
        cands = [k for k in range(n_pred) if sig(pred, k) == g]
        if not cands:  # fall back to all columns; tolerance may blur the rounded signature
            cands = list(range(n_pred))
        candidates.append(cands)
    for mapping in itertools.islice(itertools.product(*candidates), 5000):
        if len(set(mapping)) != len(mapping):
            continue
        projected = [tuple(r[k] for k in mapping) for r in pred]
        if _rows_equal(gold, projected, ordered):
            return True
    return False
