import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from gdr import config
from gdr.citations import resolve_summary
from gdr.daily_review import Breaker, review_paper
from gdr.dates import parse_partial_date
from gdr.datesource import fetch_arxiv_v1_date, fetch_crossref_dates
from gdr.dedup import dedupe, paper_keys
from gdr.fulltext import fetch_fulltext as _real_fetch_fulltext
from gdr.models import IngestDay, make_item
from gdr.relevance import score_paper
from gdr.store import Store
from gdr.summarize import summarize_edge, summarize_paper


# The journal half of the date chain: everything a later record can still
# contribute to a paper we already hold. `preprint` is deliberately not in this
# list — see `enrich_seen`.
_JOURNAL_FIELDS = ("accepted", "published", "published_precision",
                   "published_source", "received")


def _doi_of(paper) -> str:
    external = getattr(paper, "external_ids", None) or {}
    return str(getattr(paper, "doi", None) or external.get("doi") or "").strip()


def journal_dates(paper, doi: str, *, fetch_dates: bool = True) -> dict:
    """Acceptance and publication dates for one paper.

    Crossref is the only source that gives a day-precise publication date and an
    acceptance date, so it is asked first whenever a DOI is known. An ADS record
    states its own publication date, usually month-only and sometimes as
    `2026-07-00`; that is the fallback, and it is parsed rather than assumed —
    the day ADS indexed the record (`paper.published`) is not a journal date and
    must never be presented as one.
    """
    journal = {}
    if fetch_dates and doi:
        journal = fetch_crossref_dates(doi, mailto=config.CROSSREF_MAILTO)
    if paper.source == "ads" and not journal.get("published"):
        date, precision = parse_partial_date(getattr(paper, "pubdate", ""))
        if date:
            journal = {**journal, "published": date,
                       "published_precision": precision,
                       "published_source": "ads-pubdate"}
    return journal


def paper_dates(paper, ingested: str, *, fetch_dates: bool = True) -> dict:
    """The four dates for one paper. arXiv records carry their v1 date already;
    an ADS record's linked arXiv id has to be looked up to get one."""
    external = getattr(paper, "external_ids", None) or {}
    arxiv_id = str(external.get("arxiv") or "").strip()

    preprint = paper.published if paper.source == "arxiv" else ""
    if fetch_dates and not preprint and arxiv_id:
        preprint = fetch_arxiv_v1_date(arxiv_id)
    journal = journal_dates(paper, _doi_of(paper), fetch_dates=fetch_dates)
    return {
        "preprint": preprint,
        **{key: journal.get(key, "") for key in _JOURNAL_FIELDS},
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


def _locate_stored(store: Store, ingest_dates: list[str], target: str, paper):
    """The stored (day, item) pair for an already-seen paper, or None.

    The seen index already tells us which file holds it; try that file first and
    only fall back to a full scan if it turns out to be stale (e.g. a seen entry
    recorded with no matching ingest file — a legacy or test-only state, but not
    one worth crashing on)."""
    keys = paper_keys(paper)
    order = ([target] if target in ingest_dates else []) + \
            [d for d in reversed(ingest_dates) if d != target]
    for date in order:
        day = store.load_ingest(date)
        for item in day.items:
            if paper_keys(item["paper"]) & keys:
                return day, item
    return None


def _merge_identifiers(item: dict, paper) -> bool:
    """Fold a later record's identifiers into the stored paper. Pure, no network."""
    stored = item["paper"]
    changed = False
    merged = {**(getattr(paper, "external_ids", None) or {}),
              **(stored.external_ids or {})}
    if merged != (stored.external_ids or {}):
        stored.external_ids = merged
        changed = True
    doi = _doi_of(paper)
    if not stored.doi and doi:
        stored.doi = doi
        changed = True
    return changed


def enrich_seen(papers, store: Store, *, fetch_dates: bool = True) -> int:
    """Merge later-arriving identifiers and journal dates into papers we already
    hold. Without this a preprint ingested months ago would never learn that it
    was accepted and published. Never re-summarises, never re-reviews, and never
    moves a paper's archive day. Rewrites a stored ingest file only when the
    merge actually adds something new — every day is otherwise touched on every
    run for every already-seen paper in the fetch window.

    Locates the stored item BEFORE touching the network, and then asks only for
    what is missing: a paper whose journal dates are already complete costs no
    request at all. The preprint date is never fetched here — `archive_date` is
    fixed at first ingest and never recomputed, so a v1 date arriving now could
    only contradict it, which is why `_JOURNAL_FIELDS` stops short of it.
    """
    seen = store.seen_map()  # one read for the whole call, not one per key per paper
    ingest_dates = store.list_ingest_dates()
    enriched = 0
    for paper in papers:
        target = next((seen[k] for k in sorted(paper_keys(paper)) if seen.get(k)),
                      None)
        if not target:
            continue
        located = _locate_stored(store, ingest_dates, target, paper)
        if not located:
            continue
        day, item = located
        enriched += 1
        changed = _merge_identifiers(item, paper)
        missing = [key for key in _JOURNAL_FIELDS if not item["dates"].get(key)]
        if missing:
            fresh = journal_dates(paper, _doi_of(item["paper"]),
                                  fetch_dates=fetch_dates)
            for key in missing:
                if fresh.get(key):
                    item["dates"][key] = fresh[key]
                    changed = True
        if changed:
            store.save_ingest(day)
    return enriched


def repair_decisions(store: Store, llm, window_days: int | None = None,
                     sleep=time.sleep) -> int:
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


def _mark_stored_but_unseen(store: Store, candidates, stored_at: dict) -> None:
    """Record the papers the crash-window guard just caught. They are on disk but
    absent from the seen index, and `enrich_seen` locates a paper through its
    dated seen entry — without this they would be protected from re-review yet
    never gain a journal date. The stored copy's own ingest date is the right one:
    that is the day the interrupted run wrote it."""
    by_date: dict[str, set[str]] = {}
    for paper in candidates:
        keys = paper_keys(paper)
        date = next((stored_at[k] for k in sorted(keys) if stored_at.get(k)), "")
        if date:
            by_date.setdefault(date, set()).update(keys)
    for date, keys in by_date.items():
        store.mark_seen(sorted(keys), date)


def _merged_day(store: Store, run_date: str, items: list[dict]) -> IngestDay:
    """This run's harvest combined with whatever an earlier run already stored
    under the same date. `items` holds only the papers that were fresh in THIS
    run, so writing it straight out would drop the rest of the day — permanently,
    because the dropped papers stay in the seen index and are therefore never
    refetched and no longer locatable by `enrich_seen`. Already-stored entries
    win, so a paper keeps the summary and decision it was first stored with."""
    stored = (store.load_ingest(run_date).items
              if run_date in store.list_ingest_dates() else [])
    known = {it["paper"].id for it in stored}
    merged = stored + [it for it in items if it["paper"].id not in known]
    merged.sort(key=lambda it: it["paper"].id)
    return IngestDay(ingested=run_date, items=merged)


def sync(run_date, source, llm, store: Store,
         fetch_fulltext=_real_fetch_fulltext, window_days=None, max_workers=None,
         fetch_dates=True, sleep=time.sleep) -> list[str]:
    window_days = window_days or config.FETCH_WINDOW_DAYS
    max_workers = max_workers or config.MAX_CONCURRENCY

    store.ensure_seen_identities()
    papers = dedupe(source.fetch_recent(run_date, window_days))
    seen = store.seen_identities()
    candidates = [p for p in papers if seen.isdisjoint(paper_keys(p))]
    enrich_seen([p for p in papers if not seen.isdisjoint(paper_keys(p))], store,
                fetch_dates=fetch_dates)

    # Guard against the crash window between save_ingest() and mark_seen()
    # below: if a run is interrupted there, a paper is written to disk but
    # never makes it into the seen index, so the seen-index check above alone
    # would treat it as brand new on the next run — re-fetching, re-scoring,
    # re-summarising and re-reviewing it (real LLM cost) and writing a second
    # copy into a different ingest file, with both copies then rendering.
    # Cross-check against papers already stored, not just the seen index, to
    # close that window.
    stored_at = {key: it["dates"]["ingested"]
                 for it in store.all_items() for key in paper_keys(it["paper"])}
    fresh = [p for p in candidates if stored_at.keys().isdisjoint(paper_keys(p))]
    _mark_stored_but_unseen(store, candidates, stored_at)

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

    store.save_ingest(_merged_day(store, run_date, items))
    # Mark everything seen in one write, after the file is safely on disk — a
    # single read-modify-write of the seen index instead of one per paper.
    store.mark_seen(sorted({key for it in items for key in paper_keys(it["paper"])}),
                    run_date)
    return [run_date]
