"""Backfill English `authors_en` + `corresponding_en` on already-stored
core/related summaries by re-running `summarize_paper` (which reads full text).

One-time migration for data stored before these fields existed; normal `sync`
fills them inline going forward. Idempotent (skips summaries that already have
`authors_en`). Concurrent. Leaves edge items and `revisions` untouched.

Usage:
    OPENCODE_API_KEY=... python scripts/backfill_english.py
"""
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from gdr import config
from gdr.llm import OpenCodeLLM
from gdr.store import Store
from gdr.fulltext import fetch_fulltext
from gdr.summarize import summarize_paper

ROOT = Path(__file__).resolve().parent.parent


def _redo(paper, llm):
    return summarize_paper(paper, fetch_fulltext(paper), llm)


def main():
    llm = OpenCodeLLM(api_key=config.get_api_key())
    store = Store(ROOT / "data")
    for date in store.list_days():
        day = store.load_day(date)
        todo = [it for it in day.items
                if it["score"].layer in ("core", "related")
                and it["summary"] is not None
                and not it["summary"].authors_en]
        if not todo:
            continue
        with ThreadPoolExecutor(max_workers=config.MAX_CONCURRENCY) as pool:
            futs = {pool.submit(_redo, it["paper"], llm): it for it in todo}
            for fut in as_completed(futs):
                it = futs[fut]
                try:
                    it["summary"] = fut.result()
                except Exception as exc:
                    print(f"  {it['paper'].id} failed: {exc}", file=sys.stderr)
        store.save_day(day)
        print(f"{date}: refreshed {len(todo)} core/related summaries")


if __name__ == "__main__":
    main()
