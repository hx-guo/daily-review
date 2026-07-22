from gdr.models import Paper, RelevanceScore, PaperSummary, DailyReview, DayData
from gdr.store import Store


def _day(date):
    p = Paper(id="arxiv:1", source="arxiv", title="t", authors=[], abstract="",
              categories=[], published=date, url="")
    return DayData(date=date,
                   review=DailyReview(date=date, overview="o", highlights="h", trends="t"),
                   items=[{"paper": p,
                           "score": RelevanceScore(score=90, tags=["GRB"], layer="core", reason=""),
                           "summary": PaperSummary(paper_id="arxiv:1", title_zh="标题", team="",
                                                   tldr="", review="", highlight="", relation="")}])


def test_save_and_load_day(tmp_path):
    st = Store(tmp_path)
    st.save_day(_day("2026-07-18"))
    back = st.load_day("2026-07-18")
    assert back.review.overview == "o"
    assert back.items[0]["summary"].title_zh == "标题"


def test_list_days_desc(tmp_path):
    st = Store(tmp_path)
    st.save_day(_day("2026-07-17"))
    st.save_day(_day("2026-07-18"))
    assert st.list_days() == ["2026-07-18", "2026-07-17"]


def test_mark_seen_returns_new_only(tmp_path):
    st = Store(tmp_path)
    assert st.mark_seen_papers(["arxiv:1", "arxiv:2"]) == ["arxiv:1", "arxiv:2"]
    assert st.mark_seen_papers(["arxiv:2", "arxiv:3"]) == ["arxiv:3"]


def test_unseen_ids_is_readonly(tmp_path):
    st = Store(tmp_path)
    assert st.unseen_ids(["a", "b"]) == ["a", "b"]
    assert st.unseen_ids(["a", "b"]) == ["a", "b"]      # not persisted
    assert st.mark_seen_papers(["a"]) == ["a"]           # 'a' was genuinely new
    assert st.unseen_ids(["a", "b"]) == ["b"]


def test_identities_unseen_matches_any_alias(tmp_path):
    st = Store(tmp_path)
    st.mark_seen_papers(["arxiv:2607.1"])
    assert not st.identities_unseen({"ads:bib", "arxiv:2607.1", "doi:10.1/x"})
    assert st.identities_unseen({"ads:new", "doi:10.1/new"})


def test_ensure_seen_identities_backfills_legacy_daily_papers(tmp_path):
    st = Store(tmp_path)
    day = _day("2026-07-18")
    paper = day.items[0]["paper"]
    paper.title = "A Legacy GRB Paper"
    paper.doi = "10.1/legacy"
    st.save_day(day)
    st.mark_seen_papers([paper.id])  # old index format only kept the primary ID

    st.ensure_seen_identities()

    assert not st.identities_unseen({"doi:10.1/legacy"})
    assert not st.identities_unseen({"title:a legacy grb paper"})


def test_load_day_or_none(tmp_path):
    st = Store(tmp_path)
    assert st.load_day_or_none("2026-07-14") is None
    st.save_day(_day("2026-07-14"))
    assert st.load_day_or_none("2026-07-14").date == "2026-07-14"
