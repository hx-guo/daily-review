import json

from gdr.daily_review import make_daily_review
from gdr.models import Paper, PaperSummary, RelevanceScore


def _item(pid="arxiv:1", layer="core"):
    paper = Paper(id=pid, source="arxiv", title=f"paper {pid}", authors=[], abstract="",
                  categories=[], published="2026-07-18", url="")
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


def test_empty_day_skips_llm(fake_llm_factory):
    llm = fake_llm_factory([])
    review = make_daily_review("2026-07-18", [], llm)
    assert review.date == "2026-07-18"
    assert llm.calls == []
    assert "无新文献" in review.overview
    assert review.editorial_version == 2
    assert review.stories == []
