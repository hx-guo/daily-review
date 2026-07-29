import json

from gdr.models import Paper, RelevanceScore, PaperSummary, DailyReview


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


def test_relevance_from_old_dict_defaults_editorial_fields():
    old = {"score": 70, "tags": ["TDE"], "layer": "related", "reason": "相邻"}
    score = RelevanceScore.from_dict(old)
    assert score.relation == ""
    assert score.core_path == ""
    assert score.evidence == ""


def test_paper_summary_backcompat_without_english_fields():
    old = {"paper_id": "arxiv:1", "title_zh": "标题", "team": "", "tldr": "", "review": "",
           "highlight": "", "relation": ""}
    s = PaperSummary.from_dict(old)
    assert s.authors_en == "" and s.corresponding_en == ""
    # and round-trip of a full one preserves them
    s2 = PaperSummary("arxiv:2", "t", "team", "tl", "r", "h", "rel", "A (Inst)", "A")
    assert PaperSummary.from_dict(s2.to_dict()) == s2


def test_daily_review_from_old_dict_defaults_headline_fields():
    review = DailyReview.from_dict({"date": "2026-07-14", "overview": "旧概览",
                                    "highlights": "", "trends": ""})
    assert review.headline == ""
    assert review.developments == []
    assert review.editorial_version == 0
    assert review.stories == []


from gdr.models import IngestDay, item_from_dict, item_to_dict, make_item


def _ing_paper(pid="arxiv:1"):
    return Paper(id=pid, source="arxiv", title="t", authors=["A"], abstract="a",
                 categories=[], published="2026-03-12", url="")


def _ing_score():
    return RelevanceScore(score=90, tags=["GRB"], layer="core", reason="r")


def test_make_item_computes_archive_date_from_the_earliest_academic_date():
    item = make_item(_ing_paper(), _ing_score(), None,
                     dates={"preprint": "2026-03-12", "accepted": "2026-06-21",
                            "published": "2026-07-08", "ingested": "2026-07-22"})

    assert item["archive_date"] == "2026-03-12"
    assert item["dates"]["ingested"] == "2026-07-22"
    assert item["decision"] is None
    assert item["review_attempts"] == 0
    assert item["decision_final"] is False


def test_make_item_without_academic_dates_archives_under_the_ingest_day():
    """A paper we know nothing about still has to land on some calendar day."""
    item = make_item(_ing_paper(), _ing_score(), None, dates={"ingested": "2026-07-22"})

    assert item["archive_date"] == "2026-07-22"


def test_ingest_day_roundtrips_dates_and_decision():
    decision = {"level": "headline", "title": "T", "evidence": "E", "impact": "I",
                "reason": "R", "watchlist": ["w（arxiv:1）"], "reviewed_at": "2026-07-22"}
    item = make_item(_ing_paper(), _ing_score(), None,
                     dates={"preprint": "2026-03-12", "ingested": "2026-07-22"},
                     decision=decision)
    day = IngestDay(ingested="2026-07-22", items=[item])

    back = IngestDay.from_dict(json.loads(json.dumps(day.to_dict())))

    assert back.ingested == "2026-07-22"
    assert back.items[0]["paper"].id == "arxiv:1"
    assert back.items[0]["score"].layer == "core"
    assert back.items[0]["summary"] is None
    assert back.items[0]["decision"]["level"] == "headline"
    assert back.items[0]["archive_date"] == "2026-03-12"


def test_item_from_dict_defaults_missing_optional_fields():
    raw = item_to_dict(make_item(_ing_paper(), _ing_score(), None,
                                 dates={"ingested": "2026-07-22"}))
    del raw["review_attempts"], raw["decision_final"], raw["decision"]

    item = item_from_dict(raw)

    assert item["decision"] is None
    assert item["review_attempts"] == 0
    assert item["decision_final"] is False
