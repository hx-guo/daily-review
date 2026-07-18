import sys
import collections
from concurrent.futures import ThreadPoolExecutor, as_completed
from gdr import config
from gdr.dedup import dedupe
from gdr.fulltext import fetch_fulltext as _real_fetch_fulltext
from gdr.relevance import score_paper
from gdr.summarize import summarize_paper, summarize_edge
from gdr.daily_review import make_daily_review
from gdr.models import DayData, DailyReview
from gdr.store import Store


def _process_paper(paper, llm, fetch_fulltext) -> dict:
    score = score_paper(paper, llm)
    if score.layer in ("core", "related"):
        fulltext = fetch_fulltext(paper)
        summary = summarize_paper(paper, fulltext, llm)
    else:
        summary = summarize_edge(paper, llm)   # cheap Chinese title + one-liner, from abstract, no full text
    return {"paper": paper, "score": score, "summary": summary}


def _review_for(date, items, llm) -> DailyReview:
    summarized = [it for it in items if it["summary"] and it["score"].layer in ("core", "related")]
    try:
        return make_daily_review(date, summarized, llm)
    except Exception as exc:
        print(f"[gdr] daily review failed for {date}: {exc}", file=sys.stderr)
        return DailyReview(date=date, overview=f"共收录 {len(summarized)} 篇（总览生成失败）。",
                           highlights="—", trends="—")


def sync(run_date, source, llm, store: Store, fetch_fulltext=_real_fetch_fulltext,
         window_days=None, max_workers=None) -> list[str]:
    window_days = window_days or config.FETCH_WINDOW_DAYS
    max_workers = max_workers or config.MAX_CONCURRENCY

    papers = dedupe(source.fetch_recent(run_date, window_days))
    new_ids = set(store.unseen_ids([p.id for p in papers]))
    papers = [p for p in papers if p.id in new_ids]

    items = []
    if papers:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futs = {pool.submit(_process_paper, p, llm, fetch_fulltext): p for p in papers}
            for fut in as_completed(futs):
                p = futs[fut]
                try:
                    items.append(fut.result())
                except Exception as exc:  # per-paper resilience
                    print(f"[gdr] skipping {p.id}: {exc}", file=sys.stderr)

    by_date = collections.defaultdict(list)
    for it in items:
        by_date[it["paper"].published].append(it)

    affected = []
    for date in sorted(by_date):
        new_items = by_date[date]
        existing = store.load_day_or_none(date)
        if existing is not None:
            revisions = list(existing.revisions)
            revisions.append({"synced": run_date, "n_papers": len(existing.items),
                              "review": existing.review.to_dict()})
            merged = existing.items + new_items
        else:
            revisions = []
            merged = new_items
        review = _review_for(date, merged, llm)
        store.save_day(DayData(date=date, review=review, items=merged, revisions=revisions))
        affected.append(date)

    # Persist "seen" ONLY after all days are saved, and only for papers actually processed —
    # a paper skipped by an error stays unseen so the next run retries it.
    store.mark_seen_papers([it["paper"].id for it in items])
    return sorted(affected)
