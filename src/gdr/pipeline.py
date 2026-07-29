import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from gdr import config
from gdr.citations import resolve_summary
from gdr.daily_review import Breaker, review_paper
from gdr.datesource import fetch_arxiv_v1_date, fetch_crossref_dates
from gdr.dedup import dedupe, paper_keys
from gdr.fulltext import fetch_fulltext as _real_fetch_fulltext
from gdr.models import IngestDay, make_item
from gdr.relevance import score_paper
from gdr.store import Store
from gdr.summarize import summarize_edge, summarize_paper


def paper_dates(paper, ingested: str, *, fetch_dates: bool = True) -> dict:
    """The four dates for one paper. arXiv records carry their v1 date already;
    journal dates come from Crossref, which is also the only source that gives a
    day-precise publication date and an acceptance date."""
    external = getattr(paper, "external_ids", None) or {}
    arxiv_id = str(external.get("arxiv") or "").strip()
    doi = str(getattr(paper, "doi", None) or external.get("doi") or "").strip()

    preprint = paper.published if paper.source == "arxiv" else ""
    journal = {}
    if fetch_dates:
        if not preprint and arxiv_id:
            preprint = fetch_arxiv_v1_date(arxiv_id)
        if doi:
            journal = fetch_crossref_dates(doi, mailto=config.CROSSREF_MAILTO)
    if not journal and paper.source == "ads":
        journal = {"published": paper.published, "published_precision": "day",
                   "published_source": "ads-pubdate"}
    return {
        "preprint": preprint,
        "accepted": journal.get("accepted", ""),
        "published": journal.get("published", ""),
        "published_precision": journal.get("published_precision", ""),
        "published_source": journal.get("published_source", ""),
        "received": journal.get("received", ""),
        "ingested": ingested,
    }


def _process_paper(paper, llm, fetch_fulltext, run_date, breaker,
                   fetch_dates=True, sleep=time.sleep) -> dict:
    score = score_paper(paper, llm)
    if score.layer in ("core", "related"):
        fulltext = fetch_fulltext(paper)
        summary = summarize_paper(paper, fulltext, llm)
        resolve_summary(summary, ads_token=config.get_ads_token(),
                        mailto=config.CROSSREF_MAILTO)
    else:
        summary = summarize_edge(paper, llm)
    item = make_item(paper, score, summary,
                     dates=paper_dates(paper, run_date, fetch_dates=fetch_dates))
    decision = review_paper(item, llm, breaker=breaker, sleep=sleep)
    item["decision"] = decision
    if decision is None and score.layer in ("core", "related"):
        item["review_attempts"] = 1
    return item


def enrich_seen(papers, store: Store, *, fetch_dates: bool = True) -> int:
    """Merge later-arriving identifiers and journal dates into papers we already
    hold. Without this a preprint ingested months ago would never learn that it
    was accepted and published. Never re-summarises, never re-reviews, and never
    moves a paper's archive day."""
    enriched = 0
    for paper in papers:
        target = next((store.locate(k) for k in sorted(paper_keys(paper))
                       if store.locate(k)), None)
        if not target:
            continue
        external = getattr(paper, "external_ids", None) or {}
        doi = str(getattr(paper, "doi", None) or external.get("doi") or "").strip()
        fresh = paper_dates(paper, "", fetch_dates=fetch_dates)

        def mutate(item, external=external, doi=doi, fresh=fresh):
            stored = item["paper"]
            stored.external_ids = {**external, **(stored.external_ids or {})}
            if not stored.doi and doi:
                stored.doi = doi
            for key in ("accepted", "published", "published_precision",
                        "published_source", "received"):
                if not item["dates"].get(key) and fresh.get(key):
                    item["dates"][key] = fresh[key]

        matched = False
        for date in reversed(store.list_ingest_dates()):
            day = store.load_ingest(date)
            for item in day.items:
                if paper_keys(item["paper"]) & paper_keys(paper):
                    mutate(item)
                    store.save_ingest(day)
                    matched = True
                    break
            if matched:
                break
        enriched += 1 if matched else 0
    return enriched


def repair_decisions(store: Store, run_date: str, llm,
                     window_days: int | None = None, sleep=time.sleep) -> int:
    """Retry decisions that failed on an earlier run. This is the safety net for a
    dead upstream: a whole day of missing decisions comes back the next morning."""
    window_days = window_days or config.FETCH_WINDOW_DAYS
    dates = store.list_ingest_dates()[-window_days:]
    breaker = Breaker()
    repaired = 0
    for date in dates:
        day = store.load_ingest(date)
        changed = False
        for item in day.items:
            if (item.get("decision") is not None or item.get("decision_final")
                    or item["score"].layer not in ("core", "related")):
                continue
            if item.get("review_attempts", 0) >= config.REVIEW_MAX_ROUNDS:
                item["decision_final"] = True
                changed = True
                continue
            decision = review_paper(item, llm, breaker=breaker, sleep=sleep)
            item["review_attempts"] = item.get("review_attempts", 0) + 1
            if decision is not None:
                item["decision"] = decision
                repaired += 1
            elif item["review_attempts"] >= config.REVIEW_MAX_ROUNDS:
                item["decision_final"] = True
            changed = True
        if changed:
            store.save_ingest(day)
    return repaired


def sync(run_date, source, llm, store: Store,
         fetch_fulltext=_real_fetch_fulltext, window_days=None, max_workers=None,
         fetch_dates=True, sleep=time.sleep) -> list[str]:
    window_days = window_days or config.FETCH_WINDOW_DAYS
    max_workers = max_workers or config.MAX_CONCURRENCY

    store.ensure_seen_identities()
    papers = dedupe(source.fetch_recent(run_date, window_days))
    seen = store.seen_identities()
    fresh = [p for p in papers if seen.isdisjoint(paper_keys(p))]
    enrich_seen([p for p in papers if not seen.isdisjoint(paper_keys(p))], store,
                fetch_dates=fetch_dates)

    items = []
    if fresh:
        breaker = Breaker()
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futs = {pool.submit(_process_paper, p, llm, fetch_fulltext, run_date,
                                breaker, fetch_dates, sleep): p for p in fresh}
            for fut in as_completed(futs):
                paper = futs[fut]
                try:
                    items.append(fut.result())
                except Exception as exc:  # per-paper resilience
                    print(f"[gdr] skipping {paper.id}: {exc}", file=sys.stderr)

    if not items:
        return []

    items.sort(key=lambda it: it["paper"].id)
    store.save_ingest(IngestDay(ingested=run_date, items=items))
    for item in items:
        store.mark_seen(sorted(paper_keys(item["paper"])), run_date)
    return [run_date]
