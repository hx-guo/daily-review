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
    input_ids = [it["paper"].id for day in days for it in day.items]
    ingest_dates = ingest_dates_from_git(ROOT)
    missing = [pid for pid in input_ids if pid not in ingest_dates]
    print(f"{len(days)} days, {len(input_ids)} papers, "
          f"{len(ingest_dates)} ingest dates from git, {len(missing)} unresolved")

    # --dry-run only prints bucket counts, so it doesn't need real academic
    # dates — skip the network entirely to keep it instant and offline.
    resolve = ((lambda paper, ingested: paper_dates(paper, ingested, fetch_dates=False))
              if args.dry_run else paper_dates)
    out = build_ingest_days(days, ingest_dates, resolve_dates=resolve)
    output_ids = [it["paper"].id for day in out for it in day.items]
    print(f"→ {len(out)} ingest days, {len(output_ids)} papers")
    # Compare sets, not just counts: a paper duplicated across two day files
    # would keep the counts equal while hiding the duplicate.
    assert set(input_ids) == set(output_ids), \
        f"paper set changed during migration: {set(input_ids) ^ set(output_ids)}"
    assert len(output_ids) == len(set(output_ids)), \
        "duplicate paper id in migration output"

    if args.dry_run:
        for day in out:
            print(f"  {day.ingested}: {len(day.items)}")
        return
    for day in out:
        store.save_ingest(day)
    for day in out:
        # One batched mark_seen call per ingest day (not per paper): all items
        # in `day` share the same ingest date, and this is the same pattern
        # `sync` uses (see pipeline.py) to avoid hundreds of read-modify-write
        # cycles over the seen index. Date every identity alias, not just the
        # primary id: an ADS record that only matches a stored paper through
        # its DOI or normalised title must still be found by `enrich_seen`'s
        # lookup, or its journal dates would be lost forever after migration.
        keys = sorted({key for item in day.items for key in paper_keys(item["paper"])})
        store.mark_seen(keys, day.ingested)
    print("written to data/ingest/")


if __name__ == "__main__":
    main()
