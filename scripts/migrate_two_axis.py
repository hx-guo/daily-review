"""Migrate data/daily/<archive date>.json to data/ingest/<ingest date>.json.

Runs once. Needs the network (arXiv + Crossref) to resolve the three academic
dates, and the repository's git history to recover ingest dates exactly.

Usage:
    python scripts/migrate_two_axis.py --dry-run
    ADS_API_TOKEN=... python scripts/migrate_two_axis.py
"""
import argparse
from pathlib import Path

from gdr.dedup import paper_keys
from gdr.migrate import build_ingest_days, ingest_dates_from_git
from gdr.pipeline import paper_dates
from gdr.store import Store

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    store = Store(ROOT / "data")
    days = [store.load_day(d) for d in sorted(store.list_days())]
    total = sum(len(day.items) for day in days)
    ingest_dates = ingest_dates_from_git(ROOT)
    missing = [it["paper"].id for day in days for it in day.items
               if it["paper"].id not in ingest_dates]
    print(f"{len(days)} days, {total} papers, "
          f"{len(ingest_dates)} ingest dates from git, {len(missing)} unresolved")

    out = build_ingest_days(days, ingest_dates, resolve_dates=paper_dates)
    moved = sum(len(day.items) for day in out)
    print(f"→ {len(out)} ingest days, {moved} papers")
    assert moved == total, f"lost papers: {total} -> {moved}"

    if args.dry_run:
        for day in out:
            print(f"  {day.ingested}: {len(day.items)}")
        return
    for day in out:
        store.save_ingest(day)
    for day in out:
        for item in day.items:
            # Date every identity alias, not just the primary id: an ADS record
            # that only matches a stored paper through its DOI or normalised
            # title must still be found by `enrich_seen`'s lookup, or its
            # journal dates would be lost forever after migration.
            store.mark_seen(sorted(paper_keys(item["paper"])), day.ingested)
    print("written to data/ingest/")


if __name__ == "__main__":
    main()
