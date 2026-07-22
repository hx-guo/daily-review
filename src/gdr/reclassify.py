from __future__ import annotations

import datetime as dt
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from gdr import config
from gdr.pipeline import _review_for
from gdr.relevance import score_paper
from gdr.store import Store


def reclassify_day(date: str, store: Store, llm, *, synced: str | None = None,
                   max_workers: int | None = None) -> dict[str, int]:
    """Reclassify stored papers and regenerate the editorial lead without
    re-fetching papers or paying to repeat their full-text summaries."""
    day = store.load_day(date)
    old_review = day.review.to_dict()
    workers = max_workers or config.MAX_CONCURRENCY
    updated = 0
    failed = 0

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(score_paper, item["paper"], llm): item for item in day.items}
        for future in as_completed(futures):
            item = futures[future]
            try:
                item["score"] = future.result()
                updated += 1
            except Exception as exc:
                failed += 1
                print(f"[gdr] keeping old classification for {item['paper'].id}: {exc}",
                      file=sys.stderr)

    day.revisions.append({
        "synced": synced or dt.datetime.now(dt.timezone.utc).date().isoformat(),
        "n_papers": len(day.items),
        "review": old_review,
    })
    day.review = _review_for(date, day.items, llm)
    store.save_day(day)
    counts = {layer: sum(item["score"].layer == layer for item in day.items)
              for layer in ("core", "related", "edge")}
    return {"updated": updated, "failed": failed, **counts}
