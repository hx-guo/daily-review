"""Backfill the redesigned per-paper summary (亮点 + 脉络与展望 + resolved citations)
onto already-stored core/related papers by re-running `summarize_paper` (now reading
the WHOLE paper, not a truncated head) and `resolve_summary` (ADS/Crossref links).

One-time migration: re-runs every core/related paper because earlier summaries were
based on a truncated head of the text and used an older citation schema. Concurrent.
Leaves edge items and `revisions` untouched.

Usage:
    OPENCODE_API_KEY=... ADS_API_TOKEN=... python scripts/backfill_outlook.py
"""
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from gdr import config
from gdr.llm import OpenCodeLLM
from gdr.store import Store
from gdr.fulltext import fetch_fulltext
from gdr.summarize import summarize_paper
from gdr.citations import resolve_summary

ROOT = Path(__file__).resolve().parent.parent


def _redo(paper, llm):
    summary = summarize_paper(paper, fetch_fulltext(paper), llm)
    resolve_summary(summary, ads_token=config.get_ads_token(), mailto=config.CROSSREF_MAILTO)
    return summary


def main():
    llm = OpenCodeLLM(api_key=config.get_api_key())
    store = Store(ROOT / "data")
    total = 0
    for date in store.list_days():
        day = store.load_day(date)
        todo = [it for it in day.items
                if it["score"].layer in ("core", "related")
                and it["summary"] is not None]
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
        total += len(todo)
        print(f"{date}: refreshed {len(todo)} core/related summaries")
    print(f"done · {total} summaries refreshed")


if __name__ == "__main__":
    main()
