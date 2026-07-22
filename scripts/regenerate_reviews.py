"""Regenerate the daily-overview review for stored days.

Use this to recover after a synth-stage outage (e.g. a model returning errors,
which makes `sync` fall back to a "总览生成失败" placeholder) or after changing
the synth model. It reruns ONLY the daily-overview synth call over each day's
already-stored summaries — it does NOT refetch, rescore, or resummarize papers,
and it does NOT touch `revisions` (a failed placeholder is not a real version
worth archiving, so it is replaced in place).

Usage:
    OPENCODE_API_KEY=... python scripts/regenerate_reviews.py            # all days
    OPENCODE_API_KEY=... python scripts/regenerate_reviews.py 2026-07-16 # specific dates
"""
import sys
from pathlib import Path

from gdr import config
from gdr.llm import OpenCodeLLM
from gdr.store import Store
from gdr.pipeline import _review_for

ROOT = Path(__file__).resolve().parent.parent


def main():
    only = set(sys.argv[1:])
    llm = OpenCodeLLM(api_key=config.get_api_key())
    store = Store(ROOT / "data")
    for date in store.list_days():
        if only and date not in only:
            continue
        day = store.load_day(date)
        # _review_for filters to core/related only (matches the pipeline; excludes edge noise).
        core_related = [it for it in day.items
                        if it["summary"] and it["score"].layer in ("core", "related")]
        if not core_related:
            continue
        regenerated = _review_for(date, day.items, llm)
        if regenerated.overview == "新闻候选复核生成失败。":
            print(f"{date}: regeneration failed; previous review preserved",
                  file=sys.stderr)
            continue
        day.review = regenerated
        store.save_day(day)
        print(f"{date}: overview regenerated over {len(core_related)} core/related items")


if __name__ == "__main__":
    main()
