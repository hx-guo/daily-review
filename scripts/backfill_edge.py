"""Backfill light Chinese summaries (title_zh + one-line gloss) for edge papers
stored before edge-summarization existed (i.e. `summary is None`).

Uses the cheap triage-tier model from the abstract only, concurrently. Leaves
core/related items and `revisions` untouched. Safe to re-run (skips edge items
that already have a summary). One-time migration for pre-existing data; normal
`sync` runs summarize edge papers inline going forward.

Usage:
    OPENCODE_API_KEY=... python scripts/backfill_edge.py
"""
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from gdr import config
from gdr.llm import OpenCodeLLM
from gdr.store import Store
from gdr.summarize import summarize_edge

ROOT = Path(__file__).resolve().parent.parent


def main():
    llm = OpenCodeLLM(api_key=config.get_api_key())
    store = Store(ROOT / "data")
    for date in store.list_days():
        day = store.load_day(date)
        todo = [it for it in day.items if it["score"].layer == "edge" and it["summary"] is None]
        if not todo:
            continue
        with ThreadPoolExecutor(max_workers=config.MAX_CONCURRENCY) as pool:
            futs = {pool.submit(summarize_edge, it["paper"], llm): it for it in todo}
            for fut in as_completed(futs):
                it = futs[fut]
                try:
                    it["summary"] = fut.result()
                except Exception as exc:
                    print(f"  edge {it['paper'].id} failed: {exc}", file=sys.stderr)
        store.save_day(day)
        print(f"{date}: backfilled {len(todo)} edge summaries")


if __name__ == "__main__":
    main()
