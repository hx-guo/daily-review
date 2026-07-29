"""Repair decisions that failed on an earlier run.

Use this after an upstream outage (the model 400-ing for a day, say). It retries
ONLY papers whose editorial decision is missing — it never refetches, rescores or
resummarises, and never touches a decision that already succeeded.

Usage:
    OPENCODE_API_KEY=... python scripts/repair_decisions.py
"""
import datetime as dt
from pathlib import Path

from gdr import config
from gdr.llm import OpenCodeLLM
from gdr.pipeline import repair_decisions
from gdr.store import Store

ROOT = Path(__file__).resolve().parent.parent


def main():
    llm = OpenCodeLLM(api_key=config.get_api_key())
    store = Store(ROOT / "data")
    run_date = dt.datetime.now(dt.timezone.utc).date().isoformat()
    print(f"repaired {repair_decisions(store, run_date, llm)} decisions")


if __name__ == "__main__":
    main()
