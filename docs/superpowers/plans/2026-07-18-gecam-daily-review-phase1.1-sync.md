# GECAM Daily Review — Phase 1.1 (Sync Model) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace the broken "fetch exactly yesterday" model with a **sync** model: each run pulls a rolling window of recent arXiv papers, files each under its TRUE published date, backfills/merges late arrivals into their correct date (archiving prior versions), processes papers concurrently, and only ever summarizes each paper once.

**Architecture:** Builds on the existing `gdr` package (Phase 1). Changes: `ArxivSource.fetch_recent` (windowed + paginated), `DayData.revisions`, `Store.load_day_or_none`, a new `pipeline.sync` (concurrent per-paper processing + group-by-true-date + backfill with revision snapshots), revision UI in templates, and `run_daily.py` wired to `sync`.

**Tech Stack:** Python 3.11, `concurrent.futures.ThreadPoolExecutor` for bounded concurrency, existing deps.

## Global Constraints

- Python 3.11+; run tests via the venv: `.venv/bin/python -m pytest ...` (bare `pytest`/`python3` = system 3.9 — do NOT use). Full suite: `.venv/bin/python -m pytest -q`.
- Git signing is configured repo-locally — just `git commit` normally.
- Append to every commit message (after a blank line):
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Asewh3JvAnfzhVxWif5Q7R
  ```
- **Design source of truth:** spec §19 (`docs/superpowers/specs/2026-07-18-gecam-daily-review-design.md`).
- **True-date archiving:** every paper is filed under its own `published` date (`YYYY-MM-DD`), never the run/discovery date.
- **No omission:** rolling window (`FETCH_WINDOW_DAYS=7`) + `seen-index` dedup guarantees late arrivals are caught and each paper is summarized exactly once.
- **Version retention (3 layers):** git commits (full history), `DayData.revisions` (prior review snapshots), site revision-history UI.
- **Concurrency:** per-paper stages run in a `ThreadPoolExecutor(max_workers=MAX_CONCURRENCY=6)`; per-paper try/except keeps one failure from aborting the batch. Tests must be order-independent (concurrency yields nondeterministic completion order).
- Chinese output; recall-first; API key only from env `OPENCODE_API_KEY`.

---

## Task 1: Config constants

**Files:** Modify `src/gdr/config.py`; Test `tests/test_config.py`

**Interfaces:** Produces `FETCH_WINDOW_DAYS: int = 7`, `ARXIV_PAGE_SIZE: int = 100`, `MAX_CONCURRENCY: int = 6` (all env-overridable).

- [ ] **Step 1: Add the failing test** to `tests/test_config.py`:
```python
def test_sync_constants_present():
    assert config.FETCH_WINDOW_DAYS >= 1
    assert config.ARXIV_PAGE_SIZE >= 1
    assert config.MAX_CONCURRENCY >= 1
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_config.py::test_sync_constants_present -v` → FAIL (AttributeError).

- [ ] **Step 3: Add to `src/gdr/config.py`** (after `FULLTEXT_MAX_CHARS`):
```python
FETCH_WINDOW_DAYS = int(os.environ.get("GDR_FETCH_WINDOW_DAYS", "7"))
ARXIV_PAGE_SIZE = int(os.environ.get("GDR_ARXIV_PAGE_SIZE", "100"))
MAX_CONCURRENCY = int(os.environ.get("GDR_MAX_CONCURRENCY", "6"))
```

- [ ] **Step 4: Run** the full suite `.venv/bin/python -m pytest -q` → all green.

- [ ] **Step 5: Commit** `feat: add sync/concurrency config constants`

---

## Task 2: `DayData.revisions`

**Files:** Modify `src/gdr/models.py`; Test `tests/test_models.py`

**Interfaces:** `DayData(date, review, items, revisions: list[dict] = [])`. `revisions` each = `{"synced": str, "n_papers": int, "review": dict}`. `to_dict`/`from_dict` round-trip it; `from_dict` defaults missing `revisions` to `[]` (back-compat with existing files).

- [ ] **Step 1: Add the failing test** to `tests/test_models.py`:
```python
def test_daydata_revisions_roundtrip():
    p = _paper()
    review = DailyReview(date="2026-07-14", overview="o2", highlights="h2", trends="t2")
    rev = {"synced": "2026-07-16", "n_papers": 3,
           "review": DailyReview(date="2026-07-14", overview="o1", highlights="h1", trends="t1").to_dict()}
    day = DayData(date="2026-07-14", review=review,
                  items=[{"paper": p, "score": RelevanceScore(90, ["GRB"], "core", ""), "summary": None}],
                  revisions=[rev])
    back = DayData.from_dict(day.to_dict())
    assert back == day
    assert back.revisions[0]["review"]["overview"] == "o1"

def test_daydata_from_dict_without_revisions_defaults_empty():
    p = _paper()
    d = {"date": "2026-07-14",
         "review": DailyReview("2026-07-14", "o", "h", "t").to_dict(),
         "items": [{"paper": p.to_dict(), "score": RelevanceScore(90, [], "core", "").to_dict(), "summary": None}]}
    assert DayData.from_dict(d).revisions == []
```
(Note: `RelevanceScore(90, ["GRB"], "core", "")` uses positional args matching its field order `score, tags, layer, reason`.)

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_models.py -v` → the new tests FAIL.

- [ ] **Step 3: Edit `src/gdr/models.py`:**
Change the import line `from dataclasses import dataclass, asdict` → `from dataclasses import dataclass, asdict, field`.
In `DayData`, add the field:
```python
@dataclass
class DayData:
    date: str
    review: DailyReview
    items: list[dict]
    revisions: list[dict] = field(default_factory=list)
```
Update `DayData.to_dict` to include revisions (add `"revisions": self.revisions,` to the returned dict). Update `DayData.from_dict` to pass `revisions=d.get("revisions", [])`:
```python
        return cls(date=d["date"], review=DailyReview.from_dict(d["review"]),
                   items=items, revisions=d.get("revisions", []))
```

- [ ] **Step 4: Run** full suite → all green (existing DayData tests still pass; revisions defaults to `[]`).

- [ ] **Step 5: Commit** `feat: add DayData.revisions for version history`

---

## Task 3: `ArxivSource.fetch_recent` (windowed + paginated)

**Files:** Modify `src/gdr/sources/base.py`, `src/gdr/sources/arxiv_source.py`; Test `tests/test_arxiv_source.py`

**Interfaces:**
- `Source` ABC gains abstract `fetch_recent(self, end_date: str, days: int) -> list[Paper]` (keep existing abstract `fetch` too, so `ArxivSource.fetch` stays valid).
- `ArxivSource(categories, http_get=requests.get, max_results=300, page_size=config.ARXIV_PAGE_SIZE)`.
- `fetch_recent(end_date, days)` returns all papers with `start_date <= published <= end_date` where `start_date = end_date - (days-1)`, paginating by `page_size` (sorted submittedDate desc) and stopping once a page contains a paper older than `start_date` or is short.
- Refactor: extract `_entry_to_paper(entry) -> Paper` used by both `parse_atom` and a new `parse_atom_all(xml) -> list[Paper]` (no date filter).

- [ ] **Step 1: Add failing tests** to `tests/test_arxiv_source.py`:
```python
from gdr.sources.arxiv_source import parse_atom_all

def _atom(entries):  # entries: list of (id, published_date)
    items = "".join(
        f'<entry><id>http://arxiv.org/abs/{i}v1</id>'
        f'<published>{pub}T00:00:00Z</published><title>t {i}</title>'
        f'<summary>s</summary><author><name>A</name></author>'
        f'<link href="http://arxiv.org/abs/{i}v1" rel="alternate" type="text/html"/>'
        f'<category term="astro-ph.HE" scheme="http://arxiv.org/schemas/atom"/></entry>'
        for i, pub in entries)
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<feed xmlns="http://www.w3.org/2005/Atom" '
            'xmlns:arxiv="http://arxiv.org/schemas/atom">' + items + '</feed>')

def test_parse_atom_all_returns_everything():
    xml = _atom([("2607.1", "2026-07-16"), ("2607.2", "2026-07-15")])
    assert len(parse_atom_all(xml)) == 2

def test_fetch_recent_paginates_and_windows():
    all_entries = [("2607.17", "2026-07-17"), ("2607.16", "2026-07-16"),
                   ("2607.15", "2026-07-15"), ("2607.14", "2026-07-14"),
                   ("2607.13", "2026-07-13")]  # descending by submittedDate
    def fake_get(url, params=None, timeout=None):
        start = params["start"]; n = params["max_results"]
        page = all_entries[start:start + n]
        class R:
            text = _atom(page)
            def raise_for_status(self): pass
        return R()
    src = ArxivSource(["astro-ph.HE"], http_get=fake_get, page_size=2)
    got = src.fetch_recent("2026-07-16", days=3)   # window [2026-07-14, 2026-07-16]
    assert sorted(p.id for p in got) == ["arxiv:2607.14", "arxiv:2607.15", "arxiv:2607.16"]
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_arxiv_source.py -v` → new tests FAIL (ImportError parse_atom_all / no fetch_recent).

- [ ] **Step 3: Edit `src/gdr/sources/base.py`** — add the abstract method (keep the existing `fetch`):
```python
    @abstractmethod
    def fetch_recent(self, end_date: str, days: int) -> list[Paper]:
        """Return papers whose published date is within [end_date-(days-1), end_date]."""
        raise NotImplementedError
```

- [ ] **Step 4: Edit `src/gdr/sources/arxiv_source.py`:**
Add `import datetime as dt` at the top. Refactor the per-entry parsing into a helper and add `parse_atom_all` + `fetch_recent`. Replace the existing `parse_atom` body to reuse the helper:
```python
def _entry_to_paper(e) -> Paper:
    pdf_url = None
    for link in e.get("links", []):
        if link.get("title") == "pdf" or link.get("type") == "application/pdf":
            pdf_url = link.get("href")
    categories = [t.get("term") for t in e.get("tags", []) if t.get("term")]
    return Paper(
        id=_arxiv_id(e.id),
        source="arxiv",
        title=e.title.strip().replace("\n", " "),
        authors=[a.name for a in e.get("authors", [])],
        abstract=e.get("summary", "").strip().replace("\n", " "),
        categories=categories,
        published=e.get("published", "")[:10],
        url=e.get("link", ""),
        pdf_url=pdf_url,
        doi=e.get("arxiv_doi"),
    )


def parse_atom_all(xml: str) -> list[Paper]:
    feed = feedparser.parse(xml)
    return [_entry_to_paper(e) for e in feed.entries]


def parse_atom(xml: str, date: str) -> list[Paper]:
    return [p for p in parse_atom_all(xml) if p.published == date]
```
Update `ArxivSource.__init__` to accept `page_size`:
```python
    def __init__(self, categories, http_get=requests.get, max_results=300, page_size=None):
        self.categories = categories
        self._http_get = http_get
        self.max_results = max_results
        self.page_size = page_size or config.ARXIV_PAGE_SIZE
```
(Add `from gdr import config` to the imports.) Keep the existing `fetch` method as-is. Add:
```python
    def fetch_recent(self, end_date: str, days: int) -> list[Paper]:
        start_date = (dt.date.fromisoformat(end_date) - dt.timedelta(days=days - 1)).isoformat()
        query = " OR ".join(f"cat:{c}" for c in self.categories)
        collected: list[Paper] = []
        offset = 0
        while True:
            params = {"search_query": query, "start": offset, "max_results": self.page_size,
                      "sortBy": "submittedDate", "sortOrder": "descending"}
            resp = self._http_get(ARXIV_API, params=params, timeout=60)
            resp.raise_for_status()
            batch = parse_atom_all(resp.text)
            if not batch:
                break
            reached_older = False
            for p in batch:
                if p.published > end_date:
                    continue
                if p.published < start_date:
                    reached_older = True
                    continue
                collected.append(p)
            if reached_older or len(batch) < self.page_size:
                break
            offset += self.page_size
        return collected
```

- [ ] **Step 5: Run** `.venv/bin/python -m pytest tests/test_arxiv_source.py -v` → all pass (existing `parse_atom`/`fetch` tests still green). Then full suite → green.

- [ ] **Step 6: Commit** `feat: add windowed paginated fetch_recent to arxiv source`

---

## Task 4: `Store.load_day_or_none`

**Files:** Modify `src/gdr/store.py`; Test `tests/test_store.py`

**Interfaces:** `load_day_or_none(date: str) -> DayData | None` — returns the stored DayData or `None` if the file is absent (does not raise). `load_day` unchanged.

- [ ] **Step 1: Add failing test** to `tests/test_store.py`:
```python
def test_load_day_or_none(tmp_path):
    st = Store(tmp_path)
    assert st.load_day_or_none("2026-07-14") is None
    st.save_day(_day("2026-07-14"))
    assert st.load_day_or_none("2026-07-14").date == "2026-07-14"
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_store.py -v` → FAIL.

- [ ] **Step 3: Add to `src/gdr/store.py`** (after `load_day`):
```python
    def load_day_or_none(self, date: str):
        path = self.daily_dir / f"{date}.json"
        if not path.exists():
            return None
        return DayData.from_dict(json.loads(path.read_text(encoding="utf-8")))
```

- [ ] **Step 4: Run** full suite → green.

- [ ] **Step 5: Commit** `feat: add Store.load_day_or_none`

---

## Task 5: `pipeline.sync` (concurrency + true-date grouping + backfill/revisions)

**Files:** Rewrite `src/gdr/pipeline.py`; Rewrite `tests/test_pipeline.py`

**Interfaces:** `sync(run_date, source, llm, store, fetch_fulltext=<real>, window_days=None, max_workers=None) -> list[str]` returns the sorted list of affected date strings. Replaces the old `run`. Module also exposes `_process_paper(paper, llm, fetch_fulltext) -> dict`.

Behavior: `source.fetch_recent(run_date, window_days)` → dedupe → keep only `store.unseen_ids(...)` → process each new paper concurrently (per-paper try/except: a failure logs to stderr and is skipped, staying unseen) → group processed items by `paper.published` (true date) → for each affected date: load existing (or None); if existing, snapshot its current review into `revisions` (`{"synced": run_date, "n_papers": len(existing.items), "review": existing.review.to_dict()}`) and merge items, else start fresh; regenerate that date's overview over the merged summarized items (wrapped in try/except → minimal review on failure); `save_day` → after all dates saved, `mark_seen_papers([processed item ids])`.

- [ ] **Step 1: Write `tests/test_pipeline.py`** (replaces the old file — the old `run` no longer exists):
```python
import json
from gdr.models import Paper
from gdr.sources.base import Source
from gdr.store import Store
from gdr.pipeline import sync


class StubSource(Source):
    def __init__(self, papers): self._papers = papers
    def fetch(self, date): return list(self._papers)
    def fetch_recent(self, end_date, days): return list(self._papers)


def _paper(pid, title, published="2026-07-16"):
    return Paper(id=pid, source="arxiv", title=title, authors=["A"], abstract="abstract",
                 categories=["astro-ph.HE"], published=published,
                 url=f"https://arxiv.org/abs/{pid}")


def _keyed_llm(fake_llm_factory):
    return fake_llm_factory({
        "请判断这篇论文与上述范围的相关性": json.dumps({"score": 90, "tags": ["GRB"], "reason": "核心"}),
        "综述卡片": json.dumps({"title_zh": "标题", "team": "A 等", "tldr": "t",
                              "review": "r", "highlight": "h", "relation": "—"}),
        "当日总览": json.dumps({"overview": "今日 1 篇", "highlights": "H", "trends": "T"}),
    })


def test_sync_files_paper_under_its_true_date(tmp_path, fake_llm_factory):
    store = Store(tmp_path / "data")
    src = StubSource([_paper("arxiv:2607.1", "GRB", published="2026-07-14"),
                      _paper("arxiv:2607.1", "GRB", published="2026-07-14")])  # dup
    affected = sync("2026-07-18", src, _keyed_llm(fake_llm_factory), store,
                    fetch_fulltext=lambda p, **k: "BODY", max_workers=2)
    assert affected == ["2026-07-14"]
    day = store.load_day("2026-07-14")
    assert day.date == "2026-07-14"          # filed under TRUE date, not run date 07-18
    assert len(day.items) == 1               # deduped
    assert day.items[0]["summary"].title_zh == "标题"


def test_sync_skips_already_seen(tmp_path, fake_llm_factory):
    store = Store(tmp_path / "data")
    store.mark_seen_papers(["arxiv:2607.1"])
    src = StubSource([_paper("arxiv:2607.1", "GRB", published="2026-07-14")])
    affected = sync("2026-07-18", src, _keyed_llm(fake_llm_factory), store,
                    fetch_fulltext=lambda p, **k: "BODY", max_workers=2)
    assert affected == []


def test_sync_failed_paper_left_unseen(tmp_path):
    class RaisingLLM:
        def complete(self, model, system, user, temperature=0.3):
            raise RuntimeError("api down")
    store = Store(tmp_path / "data")
    src = StubSource([_paper("arxiv:2607.9", "GRB", published="2026-07-14")])
    affected = sync("2026-07-18", src, RaisingLLM(), store,
                    fetch_fulltext=lambda p, **k: "BODY", max_workers=2)
    assert affected == []                                     # nothing produced
    assert store.unseen_ids(["arxiv:2607.9"]) == ["arxiv:2607.9"]   # retried next run


def test_sync_backfill_merges_and_snapshots_revision(tmp_path, fake_llm_factory):
    store = Store(tmp_path / "data")
    # first sync: one paper on 07-14
    sync("2026-07-16", StubSource([_paper("arxiv:2607.1", "GRB A", published="2026-07-14")]),
         _keyed_llm(fake_llm_factory), store, fetch_fulltext=lambda p, **k: "BODY", max_workers=2)
    # second sync: a NEW paper also dated 07-14 arrives late
    sync("2026-07-18", StubSource([_paper("arxiv:2607.2", "GRB B", published="2026-07-14")]),
         _keyed_llm(fake_llm_factory), store, fetch_fulltext=lambda p, **k: "BODY", max_workers=2)
    day = store.load_day("2026-07-14")
    assert len(day.items) == 2                                # merged, not overwritten
    assert len(day.revisions) == 1                            # prior version snapshotted
    assert day.revisions[0]["n_papers"] == 1
    assert day.revisions[0]["synced"] == "2026-07-18"
    assert store.unseen_ids(["arxiv:2607.1", "arxiv:2607.2"]) == []   # both now seen
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_pipeline.py -v` → FAIL (ImportError: cannot import name 'sync').

- [ ] **Step 3: Rewrite `src/gdr/pipeline.py`:**
```python
import sys
import collections
from concurrent.futures import ThreadPoolExecutor, as_completed
from gdr import config
from gdr.dedup import dedupe
from gdr.fulltext import fetch_fulltext as _real_fetch_fulltext
from gdr.relevance import score_paper
from gdr.summarize import summarize_paper
from gdr.daily_review import make_daily_review
from gdr.models import DayData, DailyReview
from gdr.store import Store


def _process_paper(paper, llm, fetch_fulltext) -> dict:
    score = score_paper(paper, llm)
    summary = None
    if score.layer in ("core", "related") or config.SUMMARIZE_EDGE:
        fulltext = fetch_fulltext(paper)
        summary = summarize_paper(paper, fulltext, llm)
    return {"paper": paper, "score": score, "summary": summary}


def _review_for(date, items, llm) -> DailyReview:
    summarized = [it for it in items if it["summary"]]
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

    store.mark_seen_papers([it["paper"].id for it in items])
    return sorted(affected)
```

- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/test_pipeline.py -v` → all pass. Then full suite → green.

- [ ] **Step 5: Commit** `feat: sync pipeline with true-date archiving, backfill revisions, concurrency`

---

## Task 6: Revision-history UI + as-of date

**Files:** Modify `src/gdr/render.py`, `templates/day.html`, `templates/base.html`; Test `tests/test_render.py`

**Interfaces:** `render_site` passes `latest_date` (the newest date with papers, or None) to every render. `day.html` renders a collapsible revision history when `day.revisions` is non-empty. `base.html` shows an "as-of" note when `latest_date` is set.

- [ ] **Step 1: Add failing test** to `tests/test_render.py`:
```python
def test_render_shows_revision_history(tmp_path):
    st = Store(tmp_path / "data")
    p = Paper(id="arxiv:1", source="arxiv", title="t", authors=["A"], abstract="",
              categories=["astro-ph.HE"], published="2026-07-14",
              url="https://arxiv.org/abs/1")
    day = DayData(
        date="2026-07-14",
        review=DailyReview(date="2026-07-14", overview="new overview", highlights="", trends=""),
        items=[{"paper": p, "score": RelevanceScore(90, ["GRB"], "core", ""),
                "summary": PaperSummary("arxiv:1", "标题", "A 等", "t", "r", "h", "—")}],
        revisions=[{"synced": "2026-07-15", "n_papers": 1,
                    "review": {"date": "2026-07-14", "overview": "old overview",
                               "highlights": "", "trends": ""}}])
    st.save_day(day)
    out = tmp_path / "site"
    render_site(st, out, TEMPLATES, STATIC)
    page = (out / "day" / "2026-07-14.html").read_text(encoding="utf-8")
    assert "修订历史" in page
    assert "old overview" in page
    index = (out / "index.html").read_text(encoding="utf-8")
    assert "2026-07-14" in index   # as-of date shown on home
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_render.py -v` → new test FAILS.

- [ ] **Step 3: Edit `templates/base.html`** — add an as-of note in the header, after the `<h1>`/nav block, inside `<header>`:
```html
    {% if latest_date %}<p class="asof">数据截至 arXiv 最新公告日 {{ latest_date }}</p>{% endif %}
```

- [ ] **Step 4: Edit `templates/day.html`** — after the `</section>` that closes `.papers`, add:
```html
{% if day.revisions %}
<section class="revisions">
  <details>
    <summary>修订历史（{{ day.revisions|length }} 版）</summary>
    {% for rev in day.revisions|reverse %}
    <div class="revision">
      <h4>同步于 {{ rev.synced }} · 当时 {{ rev.n_papers }} 篇</h4>
      <p>{{ rev.review.overview }}</p>
      {% if rev.review.highlights %}<p>{{ rev.review.highlights }}</p>{% endif %}
      {% if rev.review.trends %}<p>{{ rev.review.trends }}</p>{% endif %}
    </div>
    {% endfor %}
  </details>
</section>
{% endif %}
```

- [ ] **Step 5: Edit `src/gdr/render.py`** — compute `latest_date` and pass it to every `.render(...)` call:
After `days = store.list_days()` add:
```python
    latest_date = days[0] if days else None
```
Then add `latest_date=latest_date` to each of the three `.render(...)` calls (day pages, index, archive). Example for the day render:
```python
        html = day_tmpl.render(day=day, items=items, static_prefix="../", latest_date=latest_date)
```
(and likewise `index_tmpl.render(..., latest_date=latest_date)` and `archive_tmpl.render(..., latest_date=latest_date)`).

- [ ] **Step 6: Run** `.venv/bin/python -m pytest tests/test_render.py -v` → pass (existing render tests still green). Full suite → green.

- [ ] **Step 7: Commit** `feat: revision-history UI and as-of date on the site`

---

## Task 7: Wire `run_daily.py` to `sync`

**Files:** Modify `scripts/run_daily.py`

**Interfaces:** CLI runs `sync(run_date, ...)` where `run_date` defaults to **today UTC** (window end). Uses timezone-aware UTC (no deprecated `utcnow()`).

- [ ] **Step 1: Edit `scripts/run_daily.py`:**
Replace `from gdr.pipeline import run` with `from gdr.pipeline import sync`.
Replace the date default + call:
```python
    ap.add_argument("--date", default=None, help="YYYY-MM-DD window end (default: today UTC)")
    args = ap.parse_args()
    date = args.date or dt.datetime.now(dt.timezone.utc).date().isoformat()

    llm = OpenCodeLLM(api_key=config.get_api_key())
    source = ArxivSource(categories=config.ARXIV_CATEGORIES)
    store = Store(ROOT / "data")

    affected = sync(date, source, llm, store)
    print(f"{date}: synced; affected dates: {affected}")
    render_site(store, ROOT / "site", ROOT / "templates", ROOT / "static")
```

- [ ] **Step 2: Sanity-check** the script parses and imports (do NOT execute — it makes live API calls):
`.venv/bin/python -c "import ast; ast.parse(open('scripts/run_daily.py').read()); print('ok')"`
and `.venv/bin/python -c "import scripts.run_daily" 2>/dev/null || .venv/bin/python -c "import importlib.util,pathlib; importlib.util.spec_from_file_location('rd','scripts/run_daily.py'); print('import-path ok')"` (import may run argparse only under `__main__`, which is guarded — fine).

- [ ] **Step 3: Run** the full suite → green (35 baseline + all new tests).

- [ ] **Step 4: Commit** `feat: wire run_daily to sync (today-UTC window end)`

---

## Self-Review Notes (author checklist — completed)

- **Spec coverage:** §19.1 window+pagination → Task 3; §19.2 sync/true-date/backfill → Task 5; §19.3 revisions (git is external; JSON field → Task 2; UI → Task 6); §19.4 concurrency → Task 5 (config → Task 1); §19.5 files all covered; as-of date → Task 6; run_daily → Task 7.
- **Placeholder scan:** none — every step has concrete code.
- **Type/interface consistency:** `fetch_recent(end_date, days)` defined in Task 3 ABC + impl, consumed in Task 5 (`source.fetch_recent(run_date, window_days)`) and the test StubSource; `DayData(..., revisions=[])` from Task 2 used in Task 5 (`DayData(..., revisions=revisions)`) and Task 6 tests; `load_day_or_none` from Task 4 used in Task 5; `_process_paper`/`sync` signatures consistent between Task 5 impl and tests; `revisions` entry shape `{"synced","n_papers","review":dict}` identical across Task 2/5/6.
- **Concurrency test hygiene:** all sync tests assert on sets/sorted/lengths, never on processing order; `RaisingLLM` test uses no fixture responses (order-independent).
- **Back-compat:** `DayData.from_dict` defaults `revisions=[]`, so the already-committed `data/daily/2026-07-17.json` (no revisions key) still loads.
