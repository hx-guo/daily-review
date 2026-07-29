from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from gdr import config
from gdr.relevance import score_paper
from gdr.store import Store


def reclassify_day(date: str, store: Store, llm, *,
                   max_workers: int | None = None) -> dict[str, int]:
    """Rescore one ingest day's papers with the current relevance rubric.

    Reads and writes `data/ingest/<date>.json` keyed by INGEST date — never the
    archive layout. Only `score` changes here; each item's cached `decision` is
    left untouched, so a rescore can no longer wipe out a day's already-reviewed
    headlines. There is no review/revisions snapshot to update: `compose_review`
    (called at render time, in `gdr.render.page_context`) projects the current
    `decision` values into a review on demand, for both time axes and every
    historical version of an archive day.
    """
    day = store.load_ingest(date)
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

    store.save_ingest(day)
    counts = {layer: sum(item["score"].layer == layer for item in day.items)
              for layer in ("core", "related", "edge")}
    return {"updated": updated, "failed": failed, **counts}
