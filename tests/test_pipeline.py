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
        "主题标签与相关层级是两个独立判断": json.dumps({
            "layer": "core", "score": 90, "tags": ["GRB"], "relation": "direct",
            "core_path": "science", "evidence": "GRB 是主要研究对象", "reason": "核心",
        }),
        "综述卡片": json.dumps({"title_zh": "标题", "team": "A 等", "tldr": "t",
                              "review": "r", "highlight": "h", "relation": "—"}),
        "先判断有无真正的编辑头条": json.dumps({
            "headline_level": "headline", "headline": "GRB 新进展",
            "headline_paper_id": "arxiv:2607.1", "headline_reason": "有明确结果。",
            "developments": [], "watchlist": [],
        }),
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


def test_sync_skips_ads_alias_of_seen_arxiv_paper(tmp_path, fake_llm_factory):
    store = Store(tmp_path / "data")
    store.mark_seen_papers(["arxiv:2607.1"])
    paper = _paper("ads:2026ApJ...1A", "Published GRB", published="2026-07-18")
    paper.source = "ads"
    paper.external_ids = {"ads": "2026ApJ...1A", "arxiv": "2607.1"}
    affected = sync("2026-07-18", StubSource([paper]), _keyed_llm(fake_llm_factory), store,
                    fetch_fulltext=lambda p, **k: "BODY", max_workers=2)
    assert affected == []


def test_sync_marks_all_cross_source_identifiers_seen(tmp_path, fake_llm_factory):
    store = Store(tmp_path / "data")
    paper = _paper("ads:2026ApJ...2A", "Published GRB", published="2026-07-18")
    paper.source = "ads"
    paper.doi = "10.1/published"
    paper.external_ids = {
        "ads": "2026ApJ...2A", "arxiv": "2607.2", "doi": "10.1/published"
    }
    sync("2026-07-18", StubSource([paper]), _keyed_llm(fake_llm_factory), store,
         fetch_fulltext=lambda p, **k: "BODY", max_workers=2)
    assert store.unseen_ids([
        "ads:2026apj...2a", "arxiv:2607.2", "doi:10.1/published"
    ]) == []


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


def test_sync_fans_out_to_multiple_true_dates(tmp_path, fake_llm_factory):
    store = Store(tmp_path / "data")
    src = StubSource([_paper("arxiv:a", "GRB A", published="2026-07-14"),
                      _paper("arxiv:b", "GRB B", published="2026-07-15")])
    affected = sync("2026-07-18", src, _keyed_llm(fake_llm_factory), store,
                    fetch_fulltext=lambda p, **k: "BODY", max_workers=2)
    assert affected == ["2026-07-14", "2026-07-15"]
    assert store.load_day("2026-07-14").items[0]["paper"].id == "arxiv:a"
    assert store.load_day("2026-07-15").items[0]["paper"].id == "arxiv:b"


def test_sync_edge_paper_gets_light_summary_no_fulltext(tmp_path, fake_llm_factory):
    llm = fake_llm_factory({
        "主题标签与相关层级是两个独立判断": json.dumps({
            "layer": "edge", "score": 20, "tags": [], "relation": "contextual",
            "core_path": "", "evidence": "仅背景提及", "reason": "边缘",
        }),
        "压缩成一行中文": json.dumps({"title_zh": "边缘译名", "tldr": "一句话"}),
    })
    store = Store(tmp_path / "data")
    src = StubSource([_paper("arxiv:e", "Edge paper", published="2026-07-14")])
    def no_fulltext(p, **k):
        raise AssertionError("fetch_fulltext must NOT be called for edge papers")
    affected = sync("2026-07-18", src, llm, store, fetch_fulltext=no_fulltext, max_workers=2)
    assert affected == ["2026-07-14"]
    it = store.load_day("2026-07-14").items[0]
    assert it["score"].layer == "edge"
    assert it["summary"].title_zh == "边缘译名"
    assert it["summary"].tldr == "一句话"
