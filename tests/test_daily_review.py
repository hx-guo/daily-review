import json

from gdr.daily_review import make_daily_review
from gdr.models import Paper, PaperSummary, RelevanceScore


def _item(pid="arxiv:1", layer="core", *, title=None, authors=None,
          abstract=None, doi=None):
    paper = Paper(
        id=pid, source="arxiv", title=title or f"paper {pid}",
        authors=authors if authors is not None else ["A. Researcher"],
        abstract=abstract if abstract is not None else
        "We report a directly measured transient result with quantitative evidence.",
        categories=[], published="2026-07-18", url="", doi=doi,
    )
    score = RelevanceScore(score=90, tags=["GRB"], layer=layer, reason="直接研究GRB")
    summary = PaperSummary(paper_id=pid, title_zh=f"伽马暴研究 {pid}", team="",
                           tldr="研究了伽马暴", review="", highlight="给出首次观测", relation="")
    return {"paper": paper, "score": score, "summary": summary}


def _story(pid, level="headline"):
    return {
        "paper_id": pid, "level": level, "title": f"重大进展 {pid}",
        "evidence": "摘要报告了具体的新观测结果。",
        "impact": "改变了对爆发机制的认识。",
        "reason": "结果具有明确的新颖性和科学影响。",
    }


def test_make_daily_review_uses_two_passes_and_equal_stories(fake_llm_factory):
    candidate = {"candidates": [_story("arxiv:1", "breaking")],
                 "watchlist": ["等待独立确认"]}
    verified = {"stories": [_story("arxiv:1", "breaking")],
                "watchlist": ["等待独立确认"]}
    llm = fake_llm_factory([json.dumps(candidate), json.dumps(verified)])

    review = make_daily_review("2026-07-18", [_item()], llm)

    assert review.editorial_version == 2
    assert review.stories[0]["level"] == "breaking"
    assert review.stories[0]["paper_id"] == "arxiv:1"
    assert review.headline == "" and review.headline_paper_id == ""
    assert len(llm.calls) == 2
    assert "不选择主头条" in llm.calls[0]["user"]
    assert "不选主头条" in llm.calls[1]["user"]


def test_story_count_has_no_editorial_cap(fake_llm_factory):
    items = [_item(f"arxiv:{i}") for i in range(6)]
    stories = [_story(f"arxiv:{i}", "breaking" if i % 2 else "headline")
               for i in range(6)]
    llm = fake_llm_factory([
        json.dumps({"candidates": stories, "watchlist": []}),
        json.dumps({"stories": stories, "watchlist": []}),
    ])

    review = make_daily_review("2026-07-18", items, llm)

    assert len(review.stories) == 6


def test_verifier_only_receives_material_for_nominated_papers(fake_llm_factory):
    nominated = _item("arxiv:nominated", title="NOMINATED SOURCE TITLE")
    ordinary = _item("arxiv:ordinary", title="ORDINARY SOURCE TITLE")
    story = _story("arxiv:nominated")
    llm = fake_llm_factory([
        json.dumps({"candidates": [story], "watchlist": []}),
        json.dumps({"stories": [story], "watchlist": []}),
    ])

    make_daily_review("2026-07-18", [nominated, ordinary], llm)

    assert "NOMINATED SOURCE TITLE" in llm.calls[1]["user"]
    assert "ORDINARY SOURCE TITLE" not in llm.calls[1]["user"]


def test_invalid_or_incomplete_stories_are_rejected(fake_llm_factory):
    invalid = _story("invented", "breaking")
    incomplete = _story("arxiv:1", "headline")
    incomplete["evidence"] = ""
    llm = fake_llm_factory([
        json.dumps({"candidates": [invalid, incomplete], "watchlist": []}),
        json.dumps({"stories": [invalid, incomplete], "watchlist": []}),
    ])

    review = make_daily_review("2026-07-18", [_item()], llm)

    assert review.stories == []
    assert "无达到" in review.overview


def test_secondary_nature_briefing_cannot_become_story(fake_llm_factory):
    briefing_id = "ads:2026Natur.655R.285."
    briefing = _item(
        briefing_id,
        title="Neutrino's nursery found: the `Shadow Blaster'",
        authors=[],
        abstract="A particle detected at the South Pole was born in a distant galaxy.",
        doi="10.1038/d41586-026-02034-1",
    )
    original = _item("arxiv:original")
    stories = [_story(briefing_id, "breaking"), _story("arxiv:original")]
    llm = fake_llm_factory([
        json.dumps({"candidates": stories, "watchlist": []}),
        json.dumps({"stories": stories, "watchlist": []}),
    ])

    review = make_daily_review("2026-07-18", [briefing, original], llm)

    assert [story["paper_id"] for story in review.stories] == ["arxiv:original"]
    assert briefing_id not in llm.calls[0]["user"]
    assert "原文摘要" in llm.calls[0]["user"]
    assert "不能独立作为新闻证据" in llm.calls[0]["user"]


def test_correction_and_unbylined_blurb_skip_news_review(fake_llm_factory):
    llm = fake_llm_factory([])
    correction = _item("ads:correction", title="Publisher Correction: A result")
    blurb = _item("ads:blurb", authors=[], abstract="A short editorial blurb.")

    review = make_daily_review("2026-07-18", [correction, blurb], llm)

    assert review.stories == []
    assert llm.calls == []
    assert "原始研究" in review.overview


def test_empty_day_skips_llm(fake_llm_factory):
    llm = fake_llm_factory([])
    review = make_daily_review("2026-07-18", [], llm)
    assert review.date == "2026-07-18"
    assert llm.calls == []
    assert "无新文献" in review.overview
    assert review.editorial_version == 2
    assert review.stories == []
