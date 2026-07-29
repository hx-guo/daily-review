import json
import re

from gdr.models import IngestDay, Paper, RelevanceScore, make_item
from gdr.pipeline import enrich_seen, repair_decisions, sync
from gdr.sources.base import Source
from gdr.store import Store


class StubSource(Source):
    def __init__(self, papers):
        self._papers = papers

    def fetch(self, date):
        return list(self._papers)

    def fetch_recent(self, end_date, days):
        return list(self._papers)


def _paper(pid, title=None, published="2026-07-16", source="arxiv", doi=None,
           external_ids=None):
    # Distinct per pid by default: paper_keys includes a normalised-title
    # identity, so a shared literal title would make unrelated fixture papers
    # collide as "the same paper" via title alone.
    return Paper(id=pid, source=source, title=title or f"GRB {pid}", authors=["A"],
                 abstract="abstract " * 40, categories=["astro-ph.HE"],
                 published=published, url=f"https://arxiv.org/abs/{pid}", doi=doi,
                 external_ids=external_ids or {})


def _keyed_llm(fake_llm_factory, editorial="reject"):
    def editorial_response(user):
        paper_id = re.search(r"paper_id=([^ ]+)", user).group(1)
        if "第二位、更加怀疑" in user:
            return json.dumps({"paper_id": paper_id, "decision": "headline",
                               "title": "T", "evidence": "E", "impact": "I",
                               "reason": "R", "watchlist": ["w"]})
        return json.dumps({"paper_id": paper_id, "decision": editorial,
                           "reason": "理由。"})

    return fake_llm_factory({
        "主题标签与相关层级是两个独立判断": json.dumps({
            "layer": "core", "score": 90, "tags": ["GRB"], "relation": "direct",
            "core_path": "science", "evidence": "GRB 是主要研究对象", "reason": "核心"}),
        "综述卡片": json.dumps({"title_zh": "标题", "team": "A 等", "tldr": "t",
                              "review": "r", "highlight": "h", "relation": "—"}),
        "只复核下面这一篇文献": editorial_response,
        "第二位、更加怀疑": editorial_response,
    })


def _sync(store, papers, llm, run_date="2026-07-18"):
    return sync(run_date, StubSource(papers), llm, store,
                fetch_fulltext=lambda p, **k: "BODY", max_workers=2,
                fetch_dates=False, sleep=lambda s: None)


def test_sync_writes_one_file_keyed_by_the_run_date(tmp_path, fake_llm_factory):
    store = Store(tmp_path / "data")

    affected = _sync(store, [_paper("arxiv:1", published="2026-07-14"),
                             _paper("arxiv:1", published="2026-07-14")], # dup
                     _keyed_llm(fake_llm_factory))

    assert affected == ["2026-07-18"]
    assert store.list_ingest_dates() == ["2026-07-18"]
    day = store.load_ingest("2026-07-18")
    assert len(day.items) == 1                              # deduped
    assert day.items[0]["dates"]["ingested"] == "2026-07-18"
    assert day.items[0]["dates"]["preprint"] == "2026-07-14"
    assert day.items[0]["archive_date"] == "2026-07-14"     # archive axis is the paper's own date
    assert day.items[0]["decision"]["level"] == "reject"


def test_backfill_only_pays_for_the_new_paper(tmp_path, fake_llm_factory):
    """The whole point: adding 1 paper to a big day must not re-review the day."""
    store = Store(tmp_path / "data")
    old = [_paper(f"arxiv:{i}", published="2026-07-14") for i in range(8)]
    _sync(store, old, _keyed_llm(fake_llm_factory), run_date="2026-07-18")
    before = {p: (tmp_path / "data" / "ingest" / f"{p}.json").read_bytes()
              for p in store.list_ingest_dates()}

    llm = _keyed_llm(fake_llm_factory)
    _sync(store, old + [_paper("arxiv:new", published="2026-07-14")], llm,
          run_date="2026-07-19")

    editorial = [c for c in llm.calls if "只复核下面这一篇文献" in c["user"]]
    assert len(editorial) == 1                    # only the new paper was reviewed
    assert store.list_ingest_dates() == ["2026-07-18", "2026-07-19"]
    for date, blob in before.items():
        assert (tmp_path / "data" / "ingest" / f"{date}.json").read_bytes() == blob


def test_enrich_merges_journal_dates_into_an_already_stored_paper(tmp_path):
    store = Store(tmp_path / "data")
    item = make_item(_paper("arxiv:1"), RelevanceScore(90, [], "core", "r"), None,
                     dates={"preprint": "2026-03-12", "ingested": "2026-07-18"})
    store.save_ingest(IngestDay("2026-07-18", [item]))
    store.mark_seen(["arxiv:1", "doi:10.1/x"], "2026-07-18")

    journal = _paper("ads:2026ApJ", source="ads", doi="10.1/x",
                     external_ids={"arxiv": "1", "doi": "10.1/x",
                                   "ads": "2026ApJ"})
    n = enrich_seen([journal], store, fetch_dates=False)

    stored = store.load_ingest("2026-07-18").items[0]
    assert n == 1
    assert stored["paper"].doi == "10.1/x"
    assert stored["paper"].external_ids["ads"] == "2026ApJ"
    assert stored["archive_date"] == "2026-03-12"        # archive day never moves
    assert stored["decision"] is None                    # never re-reviewed
    # ADS-sourced dates synthesise a day-precision published date even
    # without fetching Crossref; the merge must actually land it.
    assert stored["dates"]["published"] == "2026-07-16"
    assert stored["dates"]["published_precision"] == "day"
    assert stored["dates"]["published_source"] == "ads-pubdate"


def test_enrich_does_not_rewrite_the_file_when_nothing_changed(tmp_path):
    store = Store(tmp_path / "data")
    item = make_item(_paper("arxiv:9"), RelevanceScore(90, [], "core", "r"), None,
                     dates={"preprint": "2026-03-12", "ingested": "2026-07-18"})
    store.save_ingest(IngestDay("2026-07-18", [item]))
    store.mark_seen(["arxiv:9"], "2026-07-18")

    rewrites = []
    original_save = store.save_ingest

    def spy(day):
        rewrites.append(day.ingested)
        return original_save(day)

    store.save_ingest = spy

    same_paper = _paper("arxiv:9")   # nothing new: same id, no doi/external_ids/dates to add
    n = enrich_seen([same_paper], store, fetch_dates=False)

    assert n == 1          # still matched an already-stored paper
    assert rewrites == []  # ...but nothing changed, so the file was never rewritten


def test_failed_decision_still_stores_the_paper_and_is_repaired_next_run(
        tmp_path, fake_llm_factory):
    store = Store(tmp_path / "data")
    broken = fake_llm_factory({
        "主题标签与相关层级是两个独立判断": json.dumps({
            "layer": "core", "score": 90, "tags": ["GRB"], "relation": "direct",
            "core_path": "science", "evidence": "e", "reason": "核心"}),
        "综述卡片": json.dumps({"title_zh": "标题", "team": "A", "tldr": "t",
                              "review": "r", "highlight": "h", "relation": "—"}),
        "只复核下面这一篇文献": "not json",
    })

    sync("2026-07-18", StubSource([_paper("arxiv:1")]), broken, store,
         fetch_fulltext=lambda p, **k: "BODY", max_workers=1, fetch_dates=False,
         sleep=lambda s: None)

    stored = store.load_ingest("2026-07-18").items[0]
    assert stored["decision"] is None
    assert stored["review_attempts"] == 1
    assert stored["decision_final"] is False

    repaired = repair_decisions(store, _keyed_llm(fake_llm_factory))

    assert repaired == 1
    assert store.load_ingest("2026-07-18").items[0]["decision"]["level"] == "reject"


def test_repair_gives_up_after_the_configured_number_of_rounds(
        tmp_path, fake_llm_factory):
    store = Store(tmp_path / "data")
    item = make_item(_paper("arxiv:1"), RelevanceScore(90, [], "core", "r"), None,
                     dates={"ingested": "2026-07-18"})
    item["review_attempts"] = 2
    store.save_ingest(IngestDay("2026-07-18", [item]))
    broken = fake_llm_factory({"只复核下面这一篇文献": "not json"})

    assert repair_decisions(store, broken, sleep=lambda s: None) == 0

    stored = store.load_ingest("2026-07-18").items[0]
    assert stored["review_attempts"] == 3
    assert stored["decision_final"] is True

    # never tried again -- and defensively stubbed so a future regression here
    # fails fast instead of burning ~151s of real editorial backoff.
    assert repair_decisions(store, broken, sleep=lambda s: None) == 0


def test_sync_skips_already_seen_without_reprocessing(tmp_path, fake_llm_factory):
    store = Store(tmp_path / "data")
    store.mark_seen(["arxiv:1"], "2026-07-17")
    llm = _keyed_llm(fake_llm_factory)

    assert _sync(store, [_paper("arxiv:1")], llm) == []
    assert not any("综述卡片" in c["user"] for c in llm.calls)


def test_sync_does_not_duplicate_a_paper_already_stored_but_not_yet_marked_seen(
        tmp_path, fake_llm_factory):
    """Simulates a crash between save_ingest() and mark_seen(): the paper is
    already on disk, but the seen index was never updated to reflect it. The
    next sync must not treat it as brand new -- no reprocessing, no second
    stored copy."""
    store = Store(tmp_path / "data")
    paper = _paper("arxiv:1", published="2026-07-14")
    item = make_item(paper, RelevanceScore(90, [], "core", "r"), None,
                     dates={"ingested": "2026-07-18"})
    store.save_ingest(IngestDay("2026-07-18", [item]))
    # seen index deliberately left untouched -- this is the crash state.

    llm = _keyed_llm(fake_llm_factory)
    affected = _sync(store, [paper], llm, run_date="2026-07-19")

    assert affected == []
    assert store.list_ingest_dates() == ["2026-07-18"]   # no second copy written
    assert llm.calls == []                                # not reprocessed at all
