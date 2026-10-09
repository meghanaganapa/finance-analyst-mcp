"""Build the templated evaluation questions (dev + held-out) with hand-written gold SQL.

Each *family* is one business question with one gold SQL template and four paraphrase templates.
Paraphrases 1-2 go to ``dev`` (the only questions used while building the offline parser);
paraphrases 3-4 go to ``heldout``. This is a group split by paraphrase template: no held-out
wording is ever seen during development, so the parser cannot pass by memorising phrasings.

The gold SQL here is written by hand and does not import anything from the package, so the
evaluation checks the assistant's SQL against an independent answer, not against itself.

Usage: python scripts/build_questions.py
"""

from __future__ import annotations

import json
import random
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data" / "questions"

REV = "SUM(ol.quantity * ol.unit_price * (1 - ol.discount))"
SALES = "FROM orders o JOIN order_lines ol ON ol.order_id = o.order_id"
QUARTERS = {"Q1": ("01-01", "03-31"), "Q2": ("04-01", "06-30"), "Q3": ("07-01", "09-30"), "Q4": ("10-01", "12-31")}

FAMILIES = [
    {
        "family": "total_revenue",
        "slots": ["year"],
        "paraphrases": [
            "What was total revenue in {year}?",
            "Show me our {year} revenue.",
            "How much did we sell in {year} in total?",
            "Total sales for calendar year {year}, please.",
        ],
        "gold": f"SELECT ROUND({REV}, 2) {SALES} WHERE o.status = 'completed' AND substr(o.order_date, 1, 4) = '{{year}}'",
    },
    {
        "family": "revenue_by_region",
        "slots": ["year"],
        "paraphrases": [
            "Revenue by region for {year}",
            "Break down {year} revenue per region.",
            "How did each region do on sales in {year}?",
            "Which region brought in the most revenue in {year}? Show every region.",
        ],
        "gold": f"""SELECT r.region_name, ROUND({REV}, 2) {SALES}
JOIN customers c ON c.customer_id = o.customer_id JOIN regions r ON r.region_id = c.region_id
WHERE o.status = 'completed' AND substr(o.order_date, 1, 4) = '{{year}}' GROUP BY r.region_name""",
    },
    {
        "family": "top_customers_quarter",
        "slots": ["n", "quarter", "year"],
        "paraphrases": [
            "Top {n} customers by revenue in {quarter} {year}",
            "Who were our {n} biggest customers by revenue in {quarter} {year}?",
            "List the {n} highest-spending clients during {quarter} {year}.",
            "Which {n} accounts generated the most sales in {quarter} {year}?",
        ],
        "gold": f"""SELECT c.customer_name, ROUND({REV}, 2) AS revenue {SALES}
JOIN customers c ON c.customer_id = o.customer_id
WHERE o.status = 'completed' AND o.order_date BETWEEN '{{year}}-{{q_start}}' AND '{{year}}-{{q_end}}'
GROUP BY c.customer_id, c.customer_name ORDER BY revenue DESC LIMIT {{n}}""",
        "ordered": True,
    },
    {
        "family": "category_revenue_in_region",
        "slots": ["region", "year"],
        "paraphrases": [
            "Revenue by product category in the {region} region for {year}",
            "Break down {region} revenue by category in {year}.",
            "How much revenue did the {region} region make from each product category in {year}?",
            "Sales per category for {region}, {year}?",
        ],
        "gold": f"""SELECT p.category, ROUND({REV}, 2) {SALES}
JOIN products p ON p.product_id = ol.product_id JOIN customers c ON c.customer_id = o.customer_id
JOIN regions r ON r.region_id = c.region_id
WHERE o.status = 'completed' AND substr(o.order_date, 1, 4) = '{{year}}' AND r.region_name = '{{region}}'
GROUP BY p.category""",
    },
    {
        "family": "margin_pct_by_category",
        "slots": ["year"],
        "paraphrases": [
            "Gross margin % by category in {year}",
            "What was the gross margin percentage for each product category in {year}?",
            "How profitable was each category in {year}, as a margin percentage?",
            "Category margin % for {year}?",
        ],
        "gold": f"""SELECT p.category,
ROUND(100.0 * SUM(ol.quantity * (ol.unit_price * (1 - ol.discount) - p.unit_cost)) / {REV}, 1)
{SALES} JOIN products p ON p.product_id = ol.product_id
WHERE o.status = 'completed' AND substr(o.order_date, 1, 4) = '{{year}}' GROUP BY p.category""",
    },
    {
        "family": "order_count_segment",
        "slots": ["segment", "year"],
        "paraphrases": [
            "How many orders did {segment} customers place in {year}?",
            "Number of {segment} orders in {year}",
            "Count of completed orders from the {segment} segment in {year}?",
            "In {year}, how many purchases came from {segment} accounts?",
        ],
        "gold": """SELECT COUNT(DISTINCT o.order_id) FROM orders o JOIN customers c ON c.customer_id = o.customer_id
WHERE o.status = 'completed' AND substr(o.order_date, 1, 4) = '{year}' AND c.segment = '{segment}'""",
    },
    {
        "family": "monthly_revenue",
        "slots": ["year"],
        "paraphrases": [
            "Monthly revenue for {year}",
            "Show revenue by month in {year}.",
            "What's the month-by-month sales trend for {year}?",
            "Give me {year} sales for each month.",
        ],
        "gold": f"""SELECT substr(o.order_date, 1, 7) AS month, ROUND({REV}, 2) {SALES}
WHERE o.status = 'completed' AND substr(o.order_date, 1, 4) = '{{year}}' GROUP BY month ORDER BY month""",
        "ordered": True,
    },
    {
        "family": "overdue_total",
        "slots": [],
        "paraphrases": [
            "What is the total overdue amount?",
            "How much money is overdue?",
            "How much do customers owe us on invoices past their due date?",
            "Total past-due receivables right now?",
        ],
        "gold": "SELECT ROUND(SUM(amount - amount_paid), 2) FROM invoices WHERE status = 'overdue'",
    },
    {
        "family": "top_overdue_customers",
        "slots": ["n"],
        "paraphrases": [
            "Top {n} customers by overdue balance",
            "Which {n} customers have the most overdue invoices by amount?",
            "Who are the {n} worst late payers, by amount past due?",
            "List the {n} clients owing us the most on overdue invoices.",
        ],
        "gold": """SELECT c.customer_name, ROUND(SUM(i.amount - i.amount_paid), 2) AS overdue
FROM invoices i JOIN customers c ON c.customer_id = i.customer_id WHERE i.status = 'overdue'
GROUP BY c.customer_id, c.customer_name ORDER BY overdue DESC LIMIT {n}""",
        "ordered": True,
    },
    {
        "family": "expenses_by_department",
        "slots": ["year"],
        "paraphrases": [
            "Total expenses by department in {year}",
            "Break down {year} expenses per department.",
            "What did each department spend in {year}?",
            "Departmental spend for {year}?",
        ],
        "gold": """SELECT department, ROUND(SUM(amount), 2) FROM expenses
WHERE substr(expense_date, 1, 4) = '{year}' GROUP BY department""",
    },
    {
        "family": "budget_vs_actual_region",
        "slots": ["year"],
        "paraphrases": [
            "Revenue vs budget by region for {year}",
            "Compare actual revenue to budget for each region in {year}.",
            "How did each region perform against its {year} revenue budget?",
            "Budget versus actual sales per region, {year}.",
        ],
        "gold": f"""WITH a AS (SELECT c.region_id, {REV} AS rev {SALES}
  JOIN customers c ON c.customer_id = o.customer_id
  WHERE o.status = 'completed' AND substr(o.order_date, 1, 4) = '{{year}}' GROUP BY c.region_id),
b AS (SELECT region_id, SUM(revenue_budget) AS bud FROM budgets WHERE substr(month, 1, 4) = '{{year}}'
  GROUP BY region_id)
SELECT r.region_name, ROUND(a.rev, 2), ROUND(b.bud, 2), ROUND(a.rev - b.bud, 2)
FROM regions r JOIN a ON a.region_id = r.region_id JOIN b ON b.region_id = r.region_id""",
    },
    {
        "family": "aov_segment",
        "slots": ["segment", "year"],
        "paraphrases": [
            "Average order value for {segment} customers in {year}",
            "What was the AOV of {segment} accounts in {year}?",
            "On average, how much was a {segment} order worth in {year}?",
            "Mean order size in dollars for the {segment} segment, {year}?",
        ],
        "gold": f"""SELECT ROUND({REV} / COUNT(DISTINCT o.order_id), 2) {SALES}
JOIN customers c ON c.customer_id = o.customer_id
WHERE o.status = 'completed' AND substr(o.order_date, 1, 4) = '{{year}}' AND c.segment = '{{segment}}'""",
    },
    {
        "family": "bottom_products_units",
        "slots": ["n", "year"],
        "paraphrases": [
            "Bottom {n} products by units sold in {year}",
            "Which {n} products sold the fewest units in {year}?",
            "What were our {n} slowest-moving products in {year} by quantity?",
            "Name the {n} least popular items by units in {year}.",
        ],
        "gold": f"""SELECT p.product_name, SUM(ol.quantity) AS units {SALES}
JOIN products p ON p.product_id = ol.product_id
WHERE o.status = 'completed' AND substr(o.order_date, 1, 4) = '{{year}}'
GROUP BY p.product_id, p.product_name ORDER BY units ASC LIMIT {{n}}""",
        "ordered": True,
    },
    {
        "family": "revenue_growth",
        "slots": [],
        "paraphrases": [
            "What was revenue growth from 2024 to 2025?",
            "By what percentage did revenue grow in 2025 vs 2024?",
            "How much did sales increase year over year from 2024 to 2025, in percent?",
            "Year-on-year revenue change 2025 versus 2024 (%)?",
        ],
        "gold": f"""SELECT ROUND(100.0 * (SUM(CASE WHEN substr(o.order_date, 1, 4) = '2025'
  THEN ol.quantity * ol.unit_price * (1 - ol.discount) END)
  - SUM(CASE WHEN substr(o.order_date, 1, 4) = '2024' THEN ol.quantity * ol.unit_price * (1 - ol.discount) END))
  / SUM(CASE WHEN substr(o.order_date, 1, 4) = '2024' THEN ol.quantity * ol.unit_price * (1 - ol.discount) END), 1)
{SALES} WHERE o.status = 'completed'""",
    },
]

SLOT_VALUES = {
    "year": ["2024", "2025"],
    "quarter": list(QUARTERS),
    "region": ["North", "South", "East", "West"],
    "segment": ["Enterprise", "Mid-Market", "SMB"],
    "n": ["3", "5", "10"],
}


def build(seed: int = 7, per_paraphrase: int = 3) -> dict[str, list[dict]]:
    rng = random.Random(seed)
    out: dict[str, list[dict]] = {"dev": [], "heldout": []}
    for fam in FAMILIES:
        for p_idx, template in enumerate(fam["paraphrases"]):
            split = "dev" if p_idx < 2 else "heldout"
            n_inst = per_paraphrase if fam["slots"] else 1
            seen: set[tuple] = set()
            tries = 0
            while len(seen) < n_inst and tries < 50:
                tries += 1
                fill = {s: rng.choice(SLOT_VALUES[s]) for s in fam["slots"]}
                key = tuple(sorted(fill.items()))
                if key in seen:
                    continue
                seen.add(key)
                if "quarter" in fill:
                    fill["q_start"], fill["q_end"] = QUARTERS[fill["quarter"]]
                out[split].append({
                    "id": f"{split}-{fam['family']}-p{p_idx + 1}-{len(seen)}",
                    "family": fam["family"],
                    "paraphrase": p_idx + 1,
                    "question": template.format(**fill),
                    "gold_sql": " ".join(fam["gold"].format(**fill).split()),
                    "ordered": fam.get("ordered", False),
                })
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for split, rows in build().items():
        with open(OUT / f"{split}.jsonl", "w") as fh:
            for row in rows:
                fh.write(json.dumps(row) + "\n")
        print(f"{split}: {len(rows)} questions -> {OUT / (split + '.jsonl')}")


if __name__ == "__main__":
    main()
