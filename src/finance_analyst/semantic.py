"""Offline planner: a small semantic layer that maps a question to a governed metric + filters.

No LLM, no cost, fully deterministic. It understands the metrics in the business glossary, a set
of dimensions and filters, and top/bottom-N. Anything it does not understand is reported back
instead of silently ignored: unknown words send the answer to human review, and a question with
no recognisable metric is abstained on rather than guessed.

The vocabulary was built from the *dev* questions only (plus the glossary's synonyms).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

AVAILABLE_YEARS = {"2024", "2025"}
REGIONS = ["north", "south", "east", "west"]
SEGMENTS = {"enterprise": "Enterprise", "mid-market": "Mid-Market", "smb": "SMB"}
CATEGORIES = {"office supplies": "Office Supplies", "furniture": "Furniture", "technology": "Technology",
              "safety equipment": "Safety Equipment"}
QUARTERS = {"1": ("01-01", "03-31"), "2": ("04-01", "06-30"), "3": ("07-01", "09-30"), "4": ("10-01", "12-31")}

REV = "SUM(ol.quantity * ol.unit_price * (1 - ol.discount))"
GP = "SUM(ol.quantity * (ol.unit_price * (1 - ol.discount) - p.unit_cost))"

# Words the planner knows how to use or can safely ignore (from the dev set and the glossary).
KNOWN_WORDS = set("""
a an the of in for to by on at from vs versus and or with what was is were are did do does how much many
which who our we me show give break down per each total number count top bottom place placed sold
revenue sales metric value order orders units unit customers customer products product category categories
product region regions segment department departments month monthly year expenses expense spend
gross margin margin% percentage percent % profit average aov overdue amount money balance invoices invoice
budget actual compare growth grow grew biggest largest most fewest least lowest highest best worst
accounts account have has q1 q2 q3 q4 2024 2025 north south east west enterprise mid-market smb
office supplies furniture technology safety equipment please
""".split())

METRIC_LABELS = {
    "revenue": "revenue", "gross_profit": "gross_profit", "margin_pct": "gross_margin_pct", "units": "units",
    "order_count": "orders", "aov": "avg_order_value", "overdue": "overdue_amount", "expenses": "expenses",
}


@dataclass
class Plan:
    metric: str | None = None
    dimension: str | None = None
    years: list[str] = field(default_factory=list)
    quarter: str | None = None
    region: str | None = None
    segment: str | None = None
    category: str | None = None
    top_n: int | None = None
    ascending: bool = False
    unknown_words: list[str] = field(default_factory=list)
    abstain_reason: str | None = None
    sql: str | None = None

    @property
    def needs_review(self) -> bool:
        return bool(self.unknown_words)


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9%][a-z0-9%\-]*", text)


def _detect_metric(t: str) -> str | None:
    if "budget" in t:
        return "budget_vs_actual"
    if re.search(r"\bgrowth\b|\bgr[eo]w\b", t):
        return "growth"
    if "margin" in t:
        return "margin_pct" if re.search(r"%|percent", t) else "gross_profit"
    if "gross profit" in t:
        return "gross_profit"
    if re.search(r"\baov\b|average order value", t):
        return "aov"
    if "overdue" in t:
        return "overdue"
    if re.search(r"\bexpenses?\b", t):
        return "expenses"
    if re.search(r"\bunits?\b", t):
        return "units"
    if re.search(r"\borders\b", t) and re.search(r"how many|number of|count", t):
        return "order_count"
    if re.search(r"\brevenue\b|\bsales\b", t):
        return "revenue"
    return None


def _detect_dimension(t: str, metric: str, ranked: bool) -> str | None:
    if re.search(r"\bby month\b|\bmonthly\b|\bper month\b|\beach month\b", t):
        return "month"
    if re.search(r"\b(by|per|each|every) (product )?categor(y|ies)\b|\bcategory\b", t):
        return "category"
    if re.search(r"\b(by|per|each) region\b", t) or metric == "budget_vs_actual":
        return "region"
    if re.search(r"\b(by|per|each) segment\b", t):
        return "segment"
    if re.search(r"\bdepartments?\b", t):
        return "department"
    if re.search(r"\b(by|per|each) customer\b", t) or (ranked and re.search(r"\bcustomers\b", t)):
        return "customer"
    if re.search(r"\b(by|per|each) product\b", t) or (ranked and re.search(r"\bproducts\b", t)):
        return "product"
    return None


def parse(question: str) -> Plan:
    t = question.lower().strip()
    plan = Plan()

    plan.years = sorted(set(re.findall(r"\b(20\d\d)\b", t)))
    missing = [y for y in plan.years if y not in AVAILABLE_YEARS]
    if missing:
        plan.abstain_reason = f"There is no data for {', '.join(missing)} (data covers 2024-2025)."
        return plan

    plan.metric = _detect_metric(t)
    if plan.metric is None:
        plan.abstain_reason = "I could not match this question to a finance metric I know."
        return plan

    q = re.search(r"\bq([1-4])\b", t)
    plan.quarter = q.group(1) if q else None
    r = re.search(r"\b(north|south|east|west)\b", t)
    plan.region = r.group(1).title() if r else None
    for key, val in SEGMENTS.items():
        if re.search(rf"\b{key}\b", t):
            plan.segment = val
    for key, val in CATEGORIES.items():
        if key in t:
            plan.category = val

    m = re.search(r"\b(top|bottom)\s+(\d+)\b", t) or re.search(r"\b(\d+)\s+(?:\w+\s+)?(customers|products)\b", t)
    if m:
        plan.top_n = int(m.group(2) if m.group(1) in ("top", "bottom") else m.group(1))
    plan.ascending = bool(re.search(r"\b(bottom|fewest|least|lowest|worst)\b", t))
    plan.dimension = _detect_dimension(t, plan.metric, plan.top_n is not None)

    plan.unknown_words = [w for w in _tokens(t) if w not in KNOWN_WORDS and not w.isdigit()]
    if plan.quarter and len(plan.years) != 1:
        plan.unknown_words.append(f"Q{plan.quarter} without a single year")
    plan.sql = build_sql(plan)
    return plan


# ---------------------------------------------------------------- SQL builders


def _date_filters(col: str, plan: Plan) -> list[str]:
    if plan.quarter and len(plan.years) == 1:
        start, end = QUARTERS[plan.quarter]
        y = plan.years[0]
        return [f"{col} BETWEEN '{y}-{start}' AND '{y}-{end}'"]
    if len(plan.years) == 1:
        return [f"substr({col}, 1, 4) = '{plan.years[0]}'"]
    return []


def _sales_sql(plan: Plan) -> str:
    measure = {
        "revenue": f"ROUND({REV}, 2)",
        "gross_profit": f"ROUND({GP}, 2)",
        "margin_pct": f"ROUND(100.0 * {GP} / {REV}, 1)",
        "units": "SUM(ol.quantity)",
        "order_count": "COUNT(DISTINCT o.order_id)",
        "aov": f"ROUND({REV} / COUNT(DISTINCT o.order_id), 2)",
    }[plan.metric]
    need_p = plan.metric in ("gross_profit", "margin_pct") or plan.category or plan.dimension in ("category", "product")
    need_c = plan.region or plan.segment or plan.dimension in ("region", "segment", "customer")
    need_r = plan.region or plan.dimension == "region"
    joins = ["JOIN order_lines ol ON ol.order_id = o.order_id"]
    if need_p:
        joins.append("JOIN products p ON p.product_id = ol.product_id")
    if need_c:
        joins.append("JOIN customers c ON c.customer_id = o.customer_id")
    if need_r:
        joins.append("JOIN regions r ON r.region_id = c.region_id")
    where = ["o.status = 'completed'", *_date_filters("o.order_date", plan)]
    if plan.region:
        where.append(f"r.region_name = '{plan.region}'")
    if plan.segment:
        where.append(f"c.segment = '{plan.segment}'")
    if plan.category:
        where.append(f"p.category = '{plan.category}'")
    dims = {
        "region": ("r.region_name", "r.region_name"),
        "segment": ("c.segment", "c.segment"),
        "category": ("p.category", "p.category"),
        "customer": ("c.customer_name", "c.customer_id, c.customer_name"),
        "product": ("p.product_name", "p.product_id, p.product_name"),
        "month": ("substr(o.order_date, 1, 7) AS month", "month"),
    }
    return _assemble(plan, measure, "orders o", joins, where, dims)


def _invoice_sql(plan: Plan) -> str:
    measure = "ROUND(SUM(i.amount - i.amount_paid), 2)"
    joins = []
    if plan.region or plan.segment or plan.dimension in ("customer", "region", "segment"):
        joins.append("JOIN customers c ON c.customer_id = i.customer_id")
    if plan.region or plan.dimension == "region":
        joins.append("JOIN regions r ON r.region_id = c.region_id")
    where = ["i.status = 'overdue'"]
    if plan.region:
        where.append(f"r.region_name = '{plan.region}'")
    if plan.segment:
        where.append(f"c.segment = '{plan.segment}'")
    dims = {
        "customer": ("c.customer_name", "c.customer_id, c.customer_name"),
        "region": ("r.region_name", "r.region_name"),
        "segment": ("c.segment", "c.segment"),
    }
    return _assemble(plan, measure, "invoices i", joins, where, dims)


def _expense_sql(plan: Plan) -> str:
    joins = ["JOIN regions r ON r.region_id = e.region_id"] if (plan.region or plan.dimension == "region") else []
    where = _date_filters("e.expense_date", plan)
    if plan.region:
        where.append(f"r.region_name = '{plan.region}'")
    dims = {
        "department": ("e.department", "e.department"),
        "category": ("e.category", "e.category"),
        "region": ("r.region_name", "r.region_name"),
        "month": ("substr(e.expense_date, 1, 7) AS month", "month"),
    }
    return _assemble(plan, "ROUND(SUM(e.amount), 2)", "expenses e", joins, where, dims)


def _assemble(plan: Plan, measure: str, base: str, joins: list[str], where: list[str],
              dims: dict[str, tuple[str, str]]) -> str:
    label = METRIC_LABELS.get(plan.metric, "value")
    select, group = [], None
    dim = plan.dimension if plan.dimension in dims else None
    if dim:
        expr, group = dims[dim]
        select.append(expr)
    select.append(f"{measure} AS {label}")
    sql = f"SELECT {', '.join(select)} FROM {base}"
    if joins:
        sql += " " + " ".join(joins)
    if where:
        sql += " WHERE " + " AND ".join(where)
    if group:
        sql += f" GROUP BY {group}"
    if plan.top_n:
        sql += f" ORDER BY {label} {'ASC' if plan.ascending else 'DESC'} LIMIT {plan.top_n}"
    elif dim == "month":
        sql += " ORDER BY month"
    return sql


def _budget_sql(plan: Plan) -> str:
    year_f = f" AND substr(o.order_date, 1, 4) = '{plan.years[0]}'" if len(plan.years) == 1 else ""
    bud_f = f" WHERE substr(month, 1, 4) = '{plan.years[0]}'" if len(plan.years) == 1 else ""
    region_f = f" WHERE r.region_name = '{plan.region}'" if plan.region else ""
    return (
        f"WITH a AS (SELECT c.region_id, {REV} AS rev FROM orders o "
        "JOIN order_lines ol ON ol.order_id = o.order_id JOIN customers c ON c.customer_id = o.customer_id "
        f"WHERE o.status = 'completed'{year_f} GROUP BY c.region_id), "
        f"b AS (SELECT region_id, SUM(revenue_budget) AS bud FROM budgets{bud_f} GROUP BY region_id) "
        "SELECT r.region_name, ROUND(a.rev, 2) AS revenue, ROUND(b.bud, 2) AS budget, "
        "ROUND(a.rev - b.bud, 2) AS variance FROM regions r JOIN a ON a.region_id = r.region_id "
        f"JOIN b ON b.region_id = r.region_id{region_f} ORDER BY variance"
    )


def _growth_sql(plan: Plan) -> str:
    y0, y1 = (plan.years[0], plan.years[-1]) if len(plan.years) == 2 else ("2024", "2025")
    line = "ol.quantity * ol.unit_price * (1 - ol.discount)"

    def year_sum(y: str) -> str:
        return f"SUM(CASE WHEN substr(o.order_date, 1, 4) = '{y}' THEN {line} END)"

    return (
        f"SELECT ROUND(100.0 * ({year_sum(y1)} - {year_sum(y0)}) / {year_sum(y0)}, 1) AS revenue_growth_pct "
        "FROM orders o JOIN order_lines ol ON ol.order_id = o.order_id WHERE o.status = 'completed'"
    )


def build_sql(plan: Plan) -> str:
    if plan.metric == "budget_vs_actual":
        return _budget_sql(plan)
    if plan.metric == "growth":
        return _growth_sql(plan)
    if plan.metric == "overdue":
        return _invoice_sql(plan)
    if plan.metric == "expenses":
        return _expense_sql(plan)
    return _sales_sql(plan)
