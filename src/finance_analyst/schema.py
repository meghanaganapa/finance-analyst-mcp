"""What the assistant is allowed to see, plus the business glossary shared by every backend."""

from __future__ import annotations

ALLOWED_TABLES: dict[str, dict[str, str]] = {
    "regions": {
        "region_id": "Primary key",
        "region_name": "North | South | East | West",
    },
    "customers": {
        "customer_id": "Primary key",
        "customer_name": "Company name",
        "segment": "Enterprise | Mid-Market | SMB",
        "region_id": "FK -> regions",
        "signup_date": "YYYY-MM-DD",
    },
    "products": {
        "product_id": "Primary key",
        "product_name": "Product name",
        "category": "Office Supplies | Furniture | Technology | Safety Equipment",
        "unit_cost": "What one unit costs us",
        "list_price": "Catalogue price per unit",
    },
    "orders": {
        "order_id": "Primary key",
        "customer_id": "FK -> customers",
        "order_date": "YYYY-MM-DD (text)",
        "status": "completed | cancelled | returned",
    },
    "order_lines": {
        "line_id": "Primary key",
        "order_id": "FK -> orders",
        "product_id": "FK -> products",
        "quantity": "Units",
        "unit_price": "Price charged per unit before discount",
        "discount": "Fraction, e.g. 0.05 = 5%",
    },
    "invoices": {
        "invoice_id": "Primary key",
        "order_id": "FK -> orders (completed orders only)",
        "customer_id": "FK -> customers",
        "invoice_date": "YYYY-MM-DD",
        "due_date": "YYYY-MM-DD",
        "amount": "Invoice total",
        "amount_paid": "Paid so far (partial payments happen)",
        "status": "paid | open (not yet due) | overdue (past due, unpaid balance)",
    },
    "budgets": {
        "region_id": "FK -> regions",
        "month": "YYYY-MM",
        "revenue_budget": "Planned revenue for that region and month",
    },
    "expenses": {
        "expense_id": "Primary key",
        "expense_date": "YYYY-MM-DD",
        "department": "Sales | Marketing | Operations | IT | Finance",
        "category": "Expense category, e.g. Software, Travel, Freight",
        "region_id": "FK -> regions",
        "amount": "Amount spent",
    },
}

# Present in the database but never readable through the assistant.
BLOCKED_TABLES = {"employees"}
BLOCKED_COLUMNS = {("customers", "contact_email")}

GLOSSARY = """\
Business definitions (Harbourline Supplies, a B2B office and industrial supplies distributor):
- Data covers 2024-01-01 to 2025-12-31. Treat "today" as 2025-12-31.
- Revenue (also "sales") = SUM(order_lines.quantity * order_lines.unit_price * (1 - order_lines.discount))
  over orders with status = 'completed'. Cancelled and returned orders are excluded.
- Orders / order count = COUNT(DISTINCT orders.order_id) over completed orders, unless the question
  asks about cancelled or returned orders.
- Units = SUM(order_lines.quantity) over completed orders.
- Gross profit = SUM(quantity * (unit_price * (1 - discount) - products.unit_cost)) over completed orders.
- Gross margin % = 100 * gross profit / revenue.
- Average order value (AOV) = revenue / number of completed orders.
- Overdue amount = SUM(invoices.amount - invoices.amount_paid) where invoices.status = 'overdue'.
- Open receivables (not yet due) = same sum where status = 'open'.
- A customer's region is customers.region_id; dates are ISO text, so use substr(date, 1, 4) for the year.
- Quarters are calendar quarters (Q1 = Jan-Mar).
- Percentages are 0-100, rounded to 1 decimal. Money is rounded to 2 decimals.
"""


def schema_text() -> str:
    """Compact schema description for prompts and the MCP describe tools."""
    lines = []
    for table, cols in ALLOWED_TABLES.items():
        lines.append(f"TABLE {table}(")
        for col, desc in cols.items():
            lines.append(f"  {col}  -- {desc}")
        lines.append(")")
    return "\n".join(lines)
