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
    reply = json.dumps({"overview": "今日 1 篇", "highlights": "亮点是……", "trends": "趋势是……"})
    llm = fake_llm_factory([reply])
    r = make_daily_review("2026-07-18", [_item()], llm)
    assert r.date == "2026-07-18"
    assert r.overview == "今日 1 篇"
    assert "伽马暴研究" in llm.calls[0]["user"]


def test_empty_day_skips_llm(fake_llm_factory):
    llm = fake_llm_factory([])
    r = make_daily_review("2026-07-18", [], llm)
    assert r.date == "2026-07-18"
    assert llm.calls == []
    assert "无新文献" in r.overview
