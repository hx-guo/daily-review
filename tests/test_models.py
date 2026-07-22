from gdr.models import Paper, RelevanceScore, PaperSummary, DailyReview, DayData


def _paper():
    return Paper(
        id="arxiv:2607.00001",
        source="arxiv",
        title="A GRB study",
        authors=["A. Author", "B. Boss"],
        abstract="We study a GRB.",
        categories=["astro-ph.HE"],
        published="2026-07-18",
        url="https://arxiv.org/abs/2607.00001",
        pdf_url=None,
        doi=None,
    )


def test_paper_roundtrip():
    p = _paper()
    p.external_ids = {"arxiv": "2607.00001", "doi": "10.1/example"}
    assert Paper.from_dict(p.to_dict()) == p


def test_paper_from_old_dict_defaults_external_ids():
    old = _paper().to_dict()
    old.pop("external_ids")
    assert Paper.from_dict(old).external_ids == {}


def test_daydata_roundtrip():
    p = _paper()
    score = RelevanceScore(
        score=88, tags=["GRB"], layer="core", reason="direct GECAM topic"
    )
    summ = PaperSummary(
        paper_id=p.id,
        title_zh="一项伽马暴研究",
        team="A. Author 等",
        tldr="研究了一个伽马暴",
        review="……",
        highlight="……",
        relation="……",
    )
    review = DailyReview(
        date="2026-07-18", overview="今日 1 篇", highlights="……", trends="……"
    )
    day = DayData(
        date="2026-07-18",
        review=review,
        items=[{"paper": p, "score": score, "summary": summ}],
    )
    back = DayData.from_dict(day.to_dict())
    assert back == day
    assert back.items[0]["paper"].title == "A GRB study"
    assert back.items[0]["summary"].title_zh == "一项伽马暴研究"


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


def test_paper_summary_backcompat_without_english_fields():
    old = {"paper_id": "arxiv:1", "title_zh": "标题", "team": "", "tldr": "", "review": "",
           "highlight": "", "relation": ""}
    s = PaperSummary.from_dict(old)
    assert s.authors_en == "" and s.corresponding_en == ""
    # and round-trip of a full one preserves them
    s2 = PaperSummary("arxiv:2", "t", "team", "tl", "r", "h", "rel", "A (Inst)", "A")
    assert PaperSummary.from_dict(s2.to_dict()) == s2


def test_daydata_from_dict_without_revisions_defaults_empty():
    p = _paper()
    d = {"date": "2026-07-14",
         "review": DailyReview("2026-07-14", "o", "h", "t").to_dict(),
         "items": [{"paper": p.to_dict(), "score": RelevanceScore(90, [], "core", "").to_dict(), "summary": None}]}
    assert DayData.from_dict(d).revisions == []
