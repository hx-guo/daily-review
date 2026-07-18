import json
from gdr.models import Paper
from gdr.sources.base import Source
from gdr.store import Store
from gdr.pipeline import run


class StubSource(Source):
    def __init__(self, papers): self._papers = papers
    def fetch(self, date): return list(self._papers)
    def fetch_recent(self, end_date: str, days: int): return list(self._papers)


def _paper(pid, title):
    return Paper(id=f"arxiv:{pid}", source="arxiv", title=title, authors=["A"], abstract="abstract",
                 categories=["astro-ph.HE"], published="2026-07-18",
                 url=f"https://arxiv.org/abs/{pid}")


def test_pipeline_end_to_end(tmp_path, fake_llm_factory):
    # relevance (keyed by profile phrase), summary (keyed by 综述卡片), daily (keyed by 当日总览)
    # NB: "请判断..." is unique to relevance.py's prompt -- plain "GECAM" also appears inside
    # summarize.py's own JSON-schema instructions (the "relation" field example), so keying on
    # it would make the keyed FakeLLM misfire on the summarize call too.
    llm = fake_llm_factory({
        "请判断这篇论文与上述范围的相关性": json.dumps({"score": 90, "tags": ["GRB"], "reason": "核心"}),
        "综述卡片": json.dumps({"title_zh": "标题", "team": "A 等", "tldr": "t",
                              "review": "r", "highlight": "h", "relation": "—"}),
        "当日总览": json.dumps({"overview": "今日 1 篇", "highlights": "H", "trends": "T"}),
    })
    store = Store(tmp_path / "data")
    src = StubSource([_paper("2607.1", "GRB paper"), _paper("2607.1", "GRB paper")])  # dup
    day = run("2026-07-18", src, llm, store, fetch_fulltext=lambda p, **k: "BODY")
    assert len(day.items) == 1                     # deduped
    assert day.items[0]["summary"].title_zh == "标题"
    assert day.review.overview == "今日 1 篇"
    assert store.load_day("2026-07-18").items[0]["score"].layer == "core"


def test_pipeline_skips_already_seen(tmp_path, fake_llm_factory):
    llm = fake_llm_factory({
        "请判断这篇论文与上述范围的相关性": json.dumps({"score": 90, "tags": [], "reason": ""}),
        "综述卡片": json.dumps({"title_zh": "x", "team": "", "tldr": "", "review": "",
                              "highlight": "", "relation": ""}),
        "当日总览": json.dumps({"overview": "o", "highlights": "", "trends": ""}),
    })
    store = Store(tmp_path / "data")
    store.mark_seen_papers(["arxiv:2607.1"])       # pre-seen
    src = StubSource([_paper("2607.1", "GRB paper")])
    day = run("2026-07-18", src, llm, store, fetch_fulltext=lambda p, **k: "BODY")
    assert day.items == []


def test_pipeline_skips_failed_paper_and_leaves_it_unseen(tmp_path):
    class RaisingLLM:
        def complete(self, model, system, user, temperature=0.3):
            raise RuntimeError("api down")
    store = Store(tmp_path / "data")
    src = StubSource([_paper("2607.9", "GRB paper")])
    day = run("2026-07-18", src, RaisingLLM(), store, fetch_fulltext=lambda p, **k: "BODY")
    assert day.items == []                                   # the failing paper was skipped
    assert store.unseen_ids(["arxiv:2607.9"]) == ["arxiv:2607.9"]  # left unseen → retried next run
    assert store.load_day("2026-07-18").items == []          # empty day still saved


def test_pipeline_marks_processed_papers_seen(tmp_path, fake_llm_factory):
    llm = fake_llm_factory({
        "请判断这篇论文与上述范围的相关性": json.dumps({"score": 90, "tags": ["GRB"], "reason": "核心"}),
        "综述卡片": json.dumps({"title_zh": "标题", "team": "A 等", "tldr": "t",
                              "review": "r", "highlight": "h", "relation": "—"}),
        "当日总览": json.dumps({"overview": "今日 1 篇", "highlights": "H", "trends": "T"}),
    })
    store = Store(tmp_path / "data")
    src = StubSource([_paper("2607.1", "GRB paper")])
    run("2026-07-18", src, llm, store, fetch_fulltext=lambda p, **k: "BODY")
    assert store.unseen_ids(["arxiv:2607.1"]) == []          # now marked seen
