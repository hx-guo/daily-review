import sys

from gdr import config
from gdr.dedup import dedupe
from gdr.fulltext import fetch_fulltext as _real_fetch_fulltext
from gdr.relevance import score_paper
from gdr.summarize import summarize_paper
from gdr.daily_review import make_daily_review
from gdr.models import DayData, DailyReview
from gdr.store import Store


def run(date, source, llm, store: Store, fetch_fulltext=_real_fetch_fulltext) -> DayData:
    papers = dedupe(source.fetch(date))
    new_ids = set(store.unseen_ids([p.id for p in papers]))
    papers = [p for p in papers if p.id in new_ids]

    items = []
    for paper in papers:
        try:
            score = score_paper(paper, llm)
            summary = None
            if score.layer in ("core", "related") or config.SUMMARIZE_EDGE:
                fulltext = fetch_fulltext(paper)
                summary = summarize_paper(paper, fulltext, llm)
            items.append({"paper": paper, "score": score, "summary": summary})
        except Exception as exc:  # per-paper resilience: one bad paper must not abort the day
            print(f"[gdr] skipping {paper.id}: {exc}", file=sys.stderr)

    summarized = [it for it in items if it["summary"]]
    try:
        review = make_daily_review(date, summarized, llm)
    except Exception as exc:  # transport error at the synth call must not lose the day
        print(f"[gdr] daily review failed: {exc}", file=sys.stderr)
        review = DailyReview(date=date, overview=f"今日收录 {len(summarized)} 篇（总览生成失败）。",
                             highlights="—", trends="—")

    day = DayData(date=date, review=review, items=items)
    store.save_day(day)
    # Persist "seen" ONLY after the day is saved, and only for papers actually processed —
    # a paper skipped by an error stays unseen so the next run retries it.
    store.mark_seen_papers([it["paper"].id for it in items])
    return day
