"""Generate the seeded synthetic Harbourline Supplies database.

Usage: python scripts/generate_db.py [--path data/finance.db] [--seed 42]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from finance_analyst.data_gen import generate  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default=str(Path(__file__).resolve().parents[1] / "data" / "finance.db"))
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    print(f"wrote {generate(args.path, args.seed)}")
