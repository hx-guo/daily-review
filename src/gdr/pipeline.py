from gdr import config
from gdr.dedup import dedupe
from gdr.fulltext import fetch_fulltext as _real_fetch_fulltext
from gdr.relevance import score_paper
from gdr.summarize import summarize_paper
from gdr.daily_review import make_daily_review
from gdr.models import DayData
from gdr.store import Store


def run(date, source, llm, store: Store, fetch_fulltext=_real_fetch_fulltext) -> DayData:
    papers = dedupe(source.fetch(date))
    new_ids = set(store.mark_seen_papers([p.id for p in papers]))
    papers = [p for p in papers if p.id in new_ids]

    items = []
    for paper in papers:
        score = score_paper(paper, llm)
        summary = None
        if score.layer in ("core", "related") or config.SUMMARIZE_EDGE:
            fulltext = fetch_fulltext(paper)
            summary = summarize_paper(paper, fulltext, llm)
        items.append({"paper": paper, "score": score, "summary": summary})

    review = make_daily_review(date, [it for it in items if it["summary"]], llm)
    day = DayData(date=date, review=review, items=items)
    store.save_day(day)
    return day
