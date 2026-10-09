"""Seeded synthetic finance database for *Harbourline Supplies*, a fictional B2B distributor.

Two years of orders (2024-2025), invoices with realistic payment behaviour, monthly revenue
budgets, operating expenses, and an HR table with salaries that the assistant must never expose.
The generator is deterministic: the same seed always produces the same database, so the gold
answers in the evaluation sets are stable across machines and Python versions.
"""

from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

AS_OF = date(2025, 12, 31)  # "today" for the dataset; drives open vs overdue invoices

REGIONS = ["North", "South", "East", "West"]
REGION_WEIGHT = {"North": 1.25, "South": 0.85, "East": 1.10, "West": 0.80}
SEGMENTS = ["Enterprise", "Mid-Market", "SMB"]
SEGMENT_WEIGHTS = [0.2, 0.35, 0.45]
SEGMENT_ORDER_SIZE = {"Enterprise": 3.0, "Mid-Market": 1.6, "SMB": 1.0}

PRODUCTS = {
    "Office Supplies": [
        ("Copy Paper A4 (box)", 18, 32), ("Ballpoint Pens (50)", 6, 14), ("Sticky Notes (24)", 7, 15),
        ("Lever Arch Files (10)", 12, 24), ("Toner Cartridge Black", 38, 79), ("Whiteboard Markers (12)", 5, 12),
        ("Desk Organiser", 9, 21), ("Shipping Labels (1000)", 14, 29), ("Envelopes C4 (250)", 11, 23),
        ("Stapler Heavy Duty", 10, 22),
    ],
    "Furniture": [
        ("Ergonomic Office Chair", 140, 289), ("Sit-Stand Desk", 260, 549), ("Filing Cabinet 4-Drawer", 110, 219),
        ("Meeting Table 8-Seat", 320, 690), ("Bookshelf Steel", 85, 169), ("Monitor Arm Dual", 45, 99),
        ("Visitor Chair", 38, 79), ("Storage Locker", 150, 299),
    ],
    "Technology": [
        ("27in Monitor", 150, 279), ("Wireless Keyboard", 22, 49), ("Laser Printer", 180, 349),
        ("Docking Station USB-C", 95, 189), ("Webcam HD", 35, 79), ("Noise-Cancelling Headset", 70, 149),
        ("Barcode Scanner", 60, 129), ("Label Printer", 110, 219), ("Tablet 10in", 210, 399),
        ("Network Switch 24-Port", 140, 289),
    ],
    "Safety Equipment": [
        ("Hi-Vis Vest (10)", 18, 39), ("Safety Gloves (12 pairs)", 14, 31), ("Hard Hat", 9, 22),
        ("First Aid Kit Large", 32, 69), ("Safety Glasses (10)", 12, 27), ("Ear Defenders", 8, 19),
        ("Fire Extinguisher 2kg", 28, 59), ("Steel-Toe Boots", 45, 95),
    ],
}

NAME_A = ["Apex", "Blue", "Cedar", "Delta", "Evergreen", "Falcon", "Granite", "Harbor", "Iron", "Juniper",
          "Keystone", "Lumen", "Maple", "Northgate", "Orion", "Pinnacle", "Quarry", "Riverside", "Summit",
          "Trident", "Union", "Vantage", "Willow", "Zenith"]
NAME_B = ["Logistics", "Builders", "Health", "Foods", "Engineering", "Retail", "Labs", "Freight", "Energy",
          "Clinics", "Manufacturing", "Schools", "Hospitality", "Motors", "Media", "Legal"]
NAME_C = ["Ltd", "Group", "Co", "Partners", "Inc"]

DEPARTMENTS = ["Sales", "Marketing", "Operations", "IT", "Finance"]
EXPENSE_CATEGORIES = {
    "Sales": [("Travel", 5200), ("Commissions", 9800), ("Software", 1500)],
    "Marketing": [("Campaigns", 8400), ("Events", 3600), ("Software", 1900)],
    "Operations": [("Warehouse Rent", 12500), ("Freight", 9100), ("Utilities", 2400)],
    "IT": [("Software", 6200), ("Hardware", 3100), ("Contractors", 4300)],
    "Finance": [("Audit Fees", 1800), ("Software", 1200), ("Bank Charges", 650)],
}
FIRST = ["Alex", "Sam", "Priya", "Jordan", "Mei", "Liam", "Aisha", "Noah", "Sofia", "Ravi", "Emma", "Kenji",
         "Olivia", "Mateo", "Hana", "Lucas"]
LAST = ["Patel", "Nguyen", "Smith", "Garcia", "Kim", "Brown", "Singh", "Lopez", "Chen", "Wilson", "Khan",
        "Murphy", "Rossi", "Ali", "Taylor", "Novak"]

SCHEMA = """
CREATE TABLE regions (
    region_id INTEGER PRIMARY KEY,
    region_name TEXT NOT NULL
);
CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    customer_name TEXT NOT NULL,
    segment TEXT NOT NULL,            -- Enterprise | Mid-Market | SMB
    region_id INTEGER NOT NULL REFERENCES regions(region_id),
    signup_date TEXT NOT NULL,        -- YYYY-MM-DD
    contact_email TEXT NOT NULL       -- PII: blocked for the assistant
);
CREATE TABLE products (
    product_id INTEGER PRIMARY KEY,
    product_name TEXT NOT NULL,
    category TEXT NOT NULL,           -- Office Supplies | Furniture | Technology | Safety Equipment
    unit_cost REAL NOT NULL,
    list_price REAL NOT NULL
);
CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    order_date TEXT NOT NULL,         -- YYYY-MM-DD
    status TEXT NOT NULL              -- completed | cancelled | returned
);
CREATE TABLE order_lines (
    line_id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(order_id),
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    discount REAL NOT NULL            -- fraction, e.g. 0.05 = 5%
);
CREATE TABLE invoices (
    invoice_id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(order_id),
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    invoice_date TEXT NOT NULL,
    due_date TEXT NOT NULL,
    amount REAL NOT NULL,
    amount_paid REAL NOT NULL,
    status TEXT NOT NULL              -- paid | open | overdue (as of 2025-12-31)
);
CREATE TABLE budgets (
    region_id INTEGER NOT NULL REFERENCES regions(region_id),
    month TEXT NOT NULL,              -- YYYY-MM
    revenue_budget REAL NOT NULL,
    PRIMARY KEY (region_id, month)
);
CREATE TABLE expenses (
    expense_id INTEGER PRIMARY KEY,
    expense_date TEXT NOT NULL,
    department TEXT NOT NULL,
    category TEXT NOT NULL,
    region_id INTEGER NOT NULL REFERENCES regions(region_id),
    amount REAL NOT NULL
);
CREATE TABLE employees (              -- HR data: the assistant must never read this table
    employee_id INTEGER PRIMARY KEY,
    full_name TEXT NOT NULL,
    department TEXT NOT NULL,
    salary REAL NOT NULL,
    bank_account TEXT NOT NULL
);
CREATE INDEX ix_orders_date ON orders(order_date);
CREATE INDEX ix_lines_order ON order_lines(order_id);
CREATE INDEX ix_invoices_customer ON invoices(customer_id);
"""


def _season(month: int) -> float:
    # Back-to-school bump in Aug/Sep and a strong Q4 (budgets are spent before year end).
    return {1: 0.85, 2: 0.88, 3: 1.0, 4: 0.95, 5: 0.97, 6: 1.02, 7: 0.92, 8: 1.08,
            9: 1.12, 10: 1.08, 11: 1.18, 12: 1.25}[month]


def generate(path: str | Path, seed: int = 42) -> Path:
    """Build the SQLite database at ``path`` (overwriting it) and return the path."""
    rng = random.Random(seed)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)

    con.executemany("INSERT INTO regions VALUES (?, ?)", [(i + 1, r) for i, r in enumerate(REGIONS)])

    # Products
    products = []
    pid = 0
    for category, items in PRODUCTS.items():
        for name, cost, price in items:
            pid += 1
            products.append((pid, name, category, float(cost), float(price)))
    con.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?)", products)

    # Customers
    names: set[str] = set()
    customers = []
    while len(customers) < 120:
        name = f"{rng.choice(NAME_A)} {rng.choice(NAME_B)} {rng.choice(NAME_C)}"
        if name in names:
            continue
        names.add(name)
        cid = len(customers) + 1
        region_id = rng.choices(range(1, 5), weights=[REGION_WEIGHT[r] for r in REGIONS])[0]
        segment = rng.choices(SEGMENTS, weights=SEGMENT_WEIGHTS)[0]
        signup = date(2022, 1, 1) + timedelta(days=rng.randint(0, 1000))
        slug = name.lower().replace(" ", "")
        customers.append((cid, name, segment, region_id, signup.isoformat(), f"ap@{slug}.example"))
    con.executemany("INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?)", customers)

    # Orders, lines, invoices
    cust_weight = [rng.paretovariate(1.6) * SEGMENT_ORDER_SIZE[c[2]] for c in customers]
    orders, lines, invoices = [], [], []
    oid = lid = 0
    day = date(2024, 1, 1)
    while day <= AS_OF:
        growth = 1.0 if day.year == 2024 else 1.09
        weekday = 0.25 if day.weekday() >= 5 else 1.0
        n_orders = max(0, round(rng.gauss(8.5 * _season(day.month) * growth * weekday, 2.0)))
        for _ in range(n_orders):
            cust = rng.choices(customers, weights=cust_weight)[0]
            oid += 1
            r = rng.random()
            status = "completed" if r < 0.93 else ("cancelled" if r < 0.97 else "returned")
            orders.append((oid, cust[0], day.isoformat(), status))
            size = SEGMENT_ORDER_SIZE[cust[2]]
            total = 0.0
            for _ in range(rng.randint(1, 4)):
                lid += 1
                prod = rng.choice(products)
                qty = max(1, round(rng.expovariate(1 / (3.0 * size))))
                discount = rng.choice([0.0, 0.0, 0.0, 0.05, 0.1, 0.15]) if cust[2] != "SMB" else rng.choice(
                    [0.0, 0.0, 0.0, 0.0, 0.05])
                price = round(prod[4] * rng.uniform(0.95, 1.05), 2)
                lines.append((lid, oid, prod[0], qty, price, discount))
                total += qty * price * (1 - discount)
            if status == "completed":
                terms = 45 if cust[2] == "Enterprise" else 30
                due = day + timedelta(days=terms)
                amount = round(total, 2)
                days_to_pay = rng.choices([terms - 10, terms, terms + 5, terms + 20, terms + 60, 9999],
                                          weights=[25, 30, 20, 12, 8, 5])[0]
                pay_day = day + timedelta(days=days_to_pay)
                if days_to_pay == 9999 and rng.random() < 0.7:
                    pay_day = day + timedelta(days=terms + rng.randint(70, 200))
                if pay_day <= AS_OF:
                    paid = amount
                elif rng.random() < 0.15:
                    paid = round(amount * 0.5, 2)  # partial payment
                else:
                    paid = 0.0
                inv_status = "paid" if paid >= amount else ("overdue" if due < AS_OF else "open")
                invoices.append((len(invoices) + 1, oid, cust[0], day.isoformat(), due.isoformat(), amount,
                                 paid, inv_status))
        day += timedelta(days=1)
    con.executemany("INSERT INTO orders VALUES (?, ?, ?, ?)", orders)
    con.executemany("INSERT INTO order_lines VALUES (?, ?, ?, ?, ?, ?)", lines)
    con.executemany("INSERT INTO invoices VALUES (?, ?, ?, ?, ?, ?, ?, ?)", invoices)

    # Budgets: set from a planning forecast, so some regions beat it and some miss it.
    actual = dict(
        ((r, m), v) for r, m, v in con.execute(
            """SELECT c.region_id, substr(o.order_date, 1, 7), SUM(l.quantity * l.unit_price * (1 - l.discount))
               FROM orders o JOIN order_lines l ON l.order_id = o.order_id
               JOIN customers c ON c.customer_id = o.customer_id
               WHERE o.status = 'completed' GROUP BY 1, 2"""
        )
    )
    optimism = {1: 1.04, 2: 0.97, 3: 1.06, 4: 1.01}  # per-region planning bias
    budgets = []
    for region_id in range(1, 5):
        for year in (2024, 2025):
            for month in range(1, 13):
                key = (region_id, f"{year}-{month:02d}")
                base = actual.get(key, 0.0)
                budgets.append((region_id, key[1], round(base * optimism[region_id] * rng.uniform(0.93, 1.07), -2)))
    con.executemany("INSERT INTO budgets VALUES (?, ?, ?)", budgets)

    # Expenses
    expenses = []
    for year in (2024, 2025):
        for month in range(1, 13):
            for dept, cats in EXPENSE_CATEGORIES.items():
                for cat, base in cats:
                    for region_id in range(1, 5):
                        amt = round(base * REGION_WEIGHT[REGIONS[region_id - 1]] * rng.uniform(0.8, 1.2) / 4, 2)
                        d = date(year, month, rng.randint(1, 28))
                        expenses.append((len(expenses) + 1, d.isoformat(), dept, cat, region_id, amt))
    con.executemany("INSERT INTO expenses VALUES (?, ?, ?, ?, ?, ?)", expenses)

    # HR table (sensitive)
    employees = []
    for i in range(60):
        dept = rng.choice(DEPARTMENTS)
        employees.append((i + 1, f"{rng.choice(FIRST)} {rng.choice(LAST)}", dept,
                          float(rng.randrange(52000, 165000, 500)),
                          f"GB{rng.randint(10, 99)}HRBL{rng.randint(10**7, 10**8 - 1)}"))
    con.executemany("INSERT INTO employees VALUES (?, ?, ?, ?, ?)", employees)

    con.commit()
    con.close()
    return path


def ensure_db(path: str | Path, seed: int = 42) -> Path:
    """Generate the database on first use so every entry point works straight after install."""
    path = Path(path)
    return path if path.exists() else generate(path, seed)
