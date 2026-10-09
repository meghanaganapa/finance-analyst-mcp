"""Hand-written 'hard' questions with hand-written gold SQL (messy wording, multi-step logic).

Written before the assistant existed. Report-only: never tune on these. Usage: python scripts/build_hard_set.py
"""
import json
REV="SUM(ol.quantity * ol.unit_price * (1 - ol.discount))"
S="FROM orders o JOIN order_lines ol ON ol.order_id = o.order_id"
C="JOIN customers c ON c.customer_id = o.customer_id"
P="JOIN products p ON p.product_id = ol.product_id"
R="JOIN regions r ON r.region_id = c.region_id"
OK="o.status = 'completed'"
Y=lambda y: f"substr(o.order_date, 1, 4) = '{y}'"
H=[
("how much did we make last year", f"SELECT ROUND({REV},2) {S} WHERE {OK} AND {Y(2024)}", False),
("rev for the north in h1 2025", f"SELECT ROUND({REV},2) {S} {C} {R} WHERE {OK} AND r.region_name='North' AND o.order_date BETWEEN '2025-01-01' AND '2025-06-30'", False),
("Which region missed its 2025 revenue target by the most?", f"WITH a AS (SELECT c.region_id, {REV} rev {S} {C} WHERE {OK} AND {Y(2025)} GROUP BY c.region_id), b AS (SELECT region_id, SUM(revenue_budget) bud FROM budgets WHERE month LIKE '2025-%' GROUP BY region_id) SELECT r.region_name FROM regions r JOIN a USING(region_id) JOIN b USING(region_id) ORDER BY a.rev - b.bud ASC LIMIT 1", True),
("What % of our 2025 revenue came from Enterprise customers?", f"SELECT ROUND(100.0 * SUM(CASE WHEN c.segment='Enterprise' THEN ol.quantity * ol.unit_price * (1 - ol.discount) END) / {REV}, 1) {S} {C} WHERE {OK} AND {Y(2025)}", False),
("By how many dollars did Technology revenue change from 2024 to 2025?", f"SELECT ROUND(SUM(CASE WHEN {Y(2025)} THEN ol.quantity * ol.unit_price * (1 - ol.discount) ELSE 0 END) - SUM(CASE WHEN {Y(2024)} THEN ol.quantity * ol.unit_price * (1 - ol.discount) ELSE 0 END), 2) {S} {P} WHERE {OK} AND p.category='Technology'", False),
("best selling product last quarter by revenue", f"SELECT p.product_name {S} {P} WHERE {OK} AND o.order_date BETWEEN '2025-10-01' AND '2025-12-31' GROUP BY p.product_id ORDER BY {REV} DESC LIMIT 1", True),
("How many customers placed at least one order in 2025?", f"SELECT COUNT(DISTINCT o.customer_id) FROM orders o WHERE {OK} AND {Y(2025)}", False),
("What's our return rate for 2025?", f"SELECT ROUND(100.0 * SUM(CASE WHEN o.status='returned' THEN 1 ELSE 0 END) / COUNT(*), 1) FROM orders o WHERE {Y(2025)}", False),
("cancelled orders in q2 2024 - how many", "SELECT COUNT(*) FROM orders o WHERE o.status='cancelled' AND o.order_date BETWEEN '2024-04-01' AND '2024-06-30'", False),
("Which customers haven't ordered anything since September 2025?", f"SELECT c.customer_name FROM customers c JOIN orders o ON o.customer_id = c.customer_id WHERE {OK} GROUP BY c.customer_id, c.customer_name HAVING MAX(o.order_date) < '2025-10-01'", False),
("Total spend on software across all departments in 2025", "SELECT ROUND(SUM(amount),2) FROM expenses WHERE category='Software' AND substr(expense_date,1,4)='2025'", False),
("Marketing spend Q4 2025 vs Q4 2024", "SELECT substr(expense_date,1,4) AS yr, ROUND(SUM(amount),2) FROM expenses WHERE department='Marketing' AND substr(expense_date,6,2) IN ('10','11','12') GROUP BY yr ORDER BY yr", False),
("Which month in 2025 had the highest sales?", f"SELECT substr(o.order_date,1,7) {S} WHERE {OK} AND {Y(2025)} GROUP BY 1 ORDER BY {REV} DESC LIMIT 1", True),
("open receivables that aren't overdue yet", "SELECT ROUND(SUM(amount - amount_paid),2) FROM invoices WHERE status='open'", False),
("Gross profit for furniture in 2025", f"SELECT ROUND(SUM(ol.quantity * (ol.unit_price * (1 - ol.discount) - p.unit_cost)),2) {S} {P} WHERE {OK} AND {Y(2025)} AND p.category='Furniture'", False),
("Top 3 products in the West by revenue for 2025", f"SELECT p.product_name, ROUND({REV},2) rev {S} {P} {C} {R} WHERE {OK} AND {Y(2025)} AND r.region_name='West' GROUP BY p.product_id, p.product_name ORDER BY rev DESC LIMIT 3", True),
("How much budget did the East have for 2025?", "SELECT ROUND(SUM(b.revenue_budget),2) FROM budgets b JOIN regions r ON r.region_id=b.region_id WHERE r.region_name='East' AND b.month LIKE '2025-%'", False),
("Which segment has the highest average order value in 2025?", f"SELECT c.segment {S} {C} WHERE {OK} AND {Y(2025)} GROUP BY c.segment ORDER BY {REV} / COUNT(DISTINCT o.order_id) DESC LIMIT 1", True),
("Revenue from Safety Equipment in Q3 2025 in the South", f"SELECT ROUND({REV},2) {S} {P} {C} {R} WHERE {OK} AND p.category='Safety Equipment' AND r.region_name='South' AND o.order_date BETWEEN '2025-07-01' AND '2025-09-30'", False),
("operating expenses as a percentage of revenue, 2025", f"SELECT ROUND(100.0 * (SELECT SUM(amount) FROM expenses WHERE substr(expense_date,1,4)='2025') / (SELECT {REV} {S} WHERE {OK} AND {Y(2025)}), 1)", False),
("number of invoices overdue by more than 90 days", "SELECT COUNT(*) FROM invoices WHERE status='overdue' AND due_date < date('2025-12-31', '-90 days')", False),
("What's the average invoice amount for Enterprise customers?", "SELECT ROUND(AVG(i.amount),2) FROM invoices i JOIN customers c ON c.customer_id=i.customer_id WHERE c.segment='Enterprise'", False),
("Show me 2025 revenue by quarter", f"SELECT ROUND({REV},2) {S} WHERE {OK} AND {Y(2025)} GROUP BY (CAST(substr(o.order_date,6,2) AS INTEGER) + 2) / 3 ORDER BY (CAST(substr(o.order_date,6,2) AS INTEGER) + 2) / 3", True),
("how many units of the ergonomic chair did we sell in 2025", f"SELECT SUM(ol.quantity) {S} {P} WHERE {OK} AND {Y(2025)} AND p.product_name='Ergonomic Office Chair'", False),
("Which customer has the largest single unpaid invoice?", "SELECT c.customer_name FROM invoices i JOIN customers c ON c.customer_id=i.customer_id WHERE i.status <> 'paid' ORDER BY i.amount - i.amount_paid DESC LIMIT 1", True),
]
with open("data/questions/hard.jsonl","w") as f:
    for i,(q,g,o) in enumerate(H,1):
        f.write(json.dumps({"id":f"hard-{i:02d}","family":"hard","question":q,"gold_sql":" ".join(g.split()),"ordered":o})+"\n")
print(len(H))
