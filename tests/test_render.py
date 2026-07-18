from pathlib import Path
from gdr.models import Paper, RelevanceScore, PaperSummary, DailyReview, DayData
from gdr.store import Store
from gdr.render import render_site

TEMPLATES = Path(__file__).parent.parent / "templates"
STATIC = Path(__file__).parent.parent / "static"

def _item(pid, score, layer, title_zh):
    p = Paper(id=pid, source="arxiv", title="t", authors=["A"], abstract="",
              categories=["astro-ph.HE"], published="2026-07-18",
              url=f"https://arxiv.org/abs/{pid}")
    return {"paper": p,
            "score": RelevanceScore(score=score, tags=["GRB"], layer=layer, reason=""),
            "summary": PaperSummary(paper_id=pid, title_zh=title_zh, team="A 等",
                                    tldr="核心", review="综述", highlight="亮点", relation="—")}

def test_render_site(tmp_path):
    st = Store(tmp_path / "data")
    day = DayData(date="2026-07-18",
                  review=DailyReview(date="2026-07-18", overview="今日概览", highlights="H", trends="T"),
                  items=[_item("2607.2", 50, "related", "相关文章"),
                         _item("2607.1", 95, "core", "核心文章")])
    st.save_day(day)
    out = tmp_path / "site"
    render_site(st, out, TEMPLATES, STATIC)

    index = (out / "index.html").read_text(encoding="utf-8")
    assert "今日概览" in index
    # core sorts before related
    assert index.index("核心文章") < index.index("相关文章")
    assert (out / "day" / "2026-07-18.html").exists()
    assert (out / "archive.html").exists()
    assert (out / "static" / "style.css").exists()
