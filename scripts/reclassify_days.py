"""Reclassify stored days with the current editorial rubric.

This performs only the inexpensive triage calls and one daily-headline call per
day. Existing full-text summaries are reused unchanged.

Usage:
    OPENCODE_API_KEY=... python scripts/reclassify_days.py 2026-07-20 2026-07-21
    OPENCODE_API_KEY=... python scripts/reclassify_days.py --all
"""
import argparse
import datetime as dt
from pathlib import Path

from gdr import config
from gdr.llm import OpenCodeLLM
from gdr.reclassify import reclassify_day
from gdr.store import Store


ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dates", nargs="*", help="stored YYYY-MM-DD dates")
    parser.add_argument("--all", action="store_true", help="reclassify every stored day")
    args = parser.parse_args()

    store = Store(ROOT / "data")
    if args.all:
        dates = store.list_days()
    else:
        dates = args.dates
    if not dates:
        parser.error("provide at least one date or --all")
    available = set(store.list_days())
    for date in dates:
        try:
            dt.date.fromisoformat(date)
        except ValueError:
            parser.error(f"invalid date: {date}")
        if date not in available:
            parser.error(f"no stored data for {date}")

    llm = OpenCodeLLM(api_key=config.get_api_key())
    synced = dt.datetime.now(dt.timezone.utc).date().isoformat()
    for date in dates:
        result = reclassify_day(date, store, llm, synced=synced)
        print(f"{date}: reclassified; {result}")


if __name__ == "__main__":
    main()
