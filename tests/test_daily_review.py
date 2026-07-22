import json
from gdr.models import Paper, RelevanceScore, PaperSummary
from gdr.daily_review import make_daily_review


def _item(layer="core"):
    p = Paper(id="arxiv:1", source="arxiv", title="t", authors=[], abstract="",
              categories=[], published="2026-07-18", url="")
    s = RelevanceScore(score=90, tags=["GRB"], layer=layer, reason="")
    summ = PaperSummary(paper_id="arxiv:1", title_zh="伽马暴研究", team="", tldr="研究了伽马暴",
                        review="", highlight="", relation="")
    return {"paper": p, "score": s, "summary": summ}


def test_make_daily_review_parses(fake_llm_factory):
    reply = json.dumps({
        "headline_level": "breaking",
        "headline": "首次捕获磁星巨耀发高能对应体",
        "headline_paper_id": "arxiv:1",
        "headline_reason": "摘要报告了首次探测，并给出高能辐射证据。",
        "developments": [{"paper_id": "arxiv:1", "title": "磁星巨耀发",
                           "reason": "直接约束爆发机制"}],
        "watchlist": ["等待独立观测确认"],
    })
    llm = fake_llm_factory([reply])
    r = make_daily_review("2026-07-18", [_item()], llm)
    assert r.date == "2026-07-18"
    assert r.headline_level == "breaking"
    assert r.headline_paper_id == "arxiv:1"
    assert r.developments[0]["title"] == "磁星巨耀发"
    assert r.overview == r.headline_reason  # legacy representation remains useful
    assert "伽马暴研究" in llm.calls[0]["user"]
    assert "不要复述篇数" in llm.calls[0]["user"]


def test_no_headline_is_not_forced(fake_llm_factory):
    reply = json.dumps({
        "headline_level": "none", "headline": "模型随便写的标题",
        "headline_paper_id": "made-up", "headline_reason": "没有足够强的单篇结果。",
        "developments": [], "watchlist": [],
    })
    r = make_daily_review("2026-07-18", [_item()], fake_llm_factory([reply]))
    assert r.headline == "今日无突发头条"
    assert r.headline_paper_id == ""


def test_breaking_without_a_valid_supporting_paper_is_downgraded(fake_llm_factory):
    reply = json.dumps({
        "headline_level": "breaking", "headline": "夸张头条",
        "headline_paper_id": "invented", "headline_reason": "没有可追溯论文。",
        "developments": [], "watchlist": [],
    })
    r = make_daily_review("2026-07-18", [_item()], fake_llm_factory([reply]))
    assert r.headline_level == "none"
    assert r.headline == "今日无突发头条"


def test_empty_day_skips_llm(fake_llm_factory):
    llm = fake_llm_factory([])
    r = make_daily_review("2026-07-18", [], llm)
    assert r.date == "2026-07-18"
    assert llm.calls == []
    assert "无新文献" in r.overview
    assert r.headline_level == "none"
