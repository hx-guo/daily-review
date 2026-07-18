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
    assert Paper.from_dict(p.to_dict()) == p


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
