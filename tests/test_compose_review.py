import pytest

from gdr.daily_review import compose_review
from gdr.models import Paper, RelevanceScore, make_item


class ExplodingLLM:
    """compose_review must be pure; touching a model here is a test failure."""

    def complete(self, model, system, user, temperature=0.3):
        raise AssertionError("compose_review must not call the LLM")


def _item(pid, layer="core", score=90, decision=None):
    paper = Paper(id=pid, source="arxiv", title=f"t {pid}", authors=["A"],
                  abstract="a", categories=[], published="2026-07-18", url="")
    rs = RelevanceScore(score=score, tags=["GRB"], layer=layer, reason="r")
    return make_item(paper, rs, None, dates={"ingested": "2026-07-18"},
                     decision=decision)


def _decision(level, pid, watchlist=None):
    return {"level": level, "title": f"标题 {pid}", "evidence": "证据",
            "impact": "影响", "reason": "理由",
            "watchlist": watchlist if watchlist is not None else [],
            "reviewed_at": "2026-07-18"}


def test_compose_review_takes_no_llm_and_orders_breaking_before_headline():
    items = [_item("arxiv:1", score=60, decision=_decision("headline", "arxiv:1")),
             _item("arxiv:2", score=95, decision=_decision("breaking", "arxiv:2")),
             _item("arxiv:3", score=80, decision=_decision("headline", "arxiv:3")),
             _item("arxiv:4", score=99, decision=_decision("reject", "arxiv:4")),
             _item("arxiv:5", layer="edge", score=10)]

    review = compose_review("2026-07-18", items)

    assert [s["paper_id"] for s in review.stories] == ["arxiv:2", "arxiv:3", "arxiv:1"]
    assert [s["level"] for s in review.stories] == ["breaking", "headline", "headline"]
    assert review.stories[0]["impact"] == "影响"
    assert review.editorial_version == 2


def test_compose_review_is_pure_and_repeatable():
    items = [_item("arxiv:1", decision=_decision("headline", "arxiv:1"))]

    first = compose_review("2026-07-18", items)
    second = compose_review("2026-07-18", items)

    assert first.to_dict() == second.to_dict()


def test_watchlist_is_concatenated_in_story_order_and_deduped():
    items = [_item("arxiv:1", score=95,
                   decision=_decision("breaking", "arxiv:1",
                                      ["等待独立确认（arxiv:1）", "共用信号（arxiv:1）"])),
             _item("arxiv:2", score=80,
                   decision=_decision("headline", "arxiv:2", ["共用信号（arxiv:1）"])),
             _item("arxiv:3", score=99,
                   decision=_decision("reject", "arxiv:3", ["被拒的不算"]))]

    review = compose_review("2026-07-18", items)

    assert review.watchlist == ["等待独立确认（arxiv:1）", "共用信号（arxiv:1）"]


def test_quiet_day_overview_counts_core_and_related_only():
    items = [_item("arxiv:1", decision=_decision("reject", "arxiv:1")),
             _item("arxiv:2", layer="related", score=50,
                   decision=_decision("reject", "arxiv:2")),
             _item("arxiv:3", layer="edge", score=10)]

    review = compose_review("2026-07-18", items)

    assert review.stories == []
    assert review.overview == "当日 2 篇核心与相关文献均为常规推进，核心 1 篇已按优先级列于下方。"


def test_day_with_nothing_reviewed_says_no_original_research_met_the_bar():
    items = [_item("arxiv:1", layer="edge", score=10)]

    review = compose_review("2026-07-18", items)

    assert review.overview == "当日 0 篇核心与相关文献中无原始研究达到新闻门槛。"


def test_empty_day():
    review = compose_review("2026-07-18", [])

    assert review.overview == "今日无新文献。"
    assert review.stories == []
    assert review.editorial_version == 2
