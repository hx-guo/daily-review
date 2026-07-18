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


def test_render_edge_card_no_dangling_labels(tmp_path):
    st = Store(tmp_path / "data")
    p = Paper(id="arxiv:e1", source="arxiv", title="Edge Paper Title", authors=["A"],
              abstract="edge abstract text", categories=["astro-ph.HE"], published="2026-07-18",
              url="https://arxiv.org/abs/e1")
    day = DayData(date="2026-07-18",
                  review=DailyReview(date="2026-07-18", overview="o", highlights="h", trends="t"),
                  items=[{"paper": p, "score": RelevanceScore(score=10, tags=[], layer="edge", reason=""),
                          "summary": None}])
    st.save_day(day)
    out = tmp_path / "site"
    render_site(st, out, TEMPLATES, STATIC)
    page = (out / "day" / "2026-07-18.html").read_text(encoding="utf-8")
    assert "Edge Paper Title" in page
    assert "edge abstract text" in page
    assert "TL;DR：" not in page


def test_render_shows_revision_history(tmp_path):
    st = Store(tmp_path / "data")
    p = Paper(id="arxiv:1", source="arxiv", title="t", authors=["A"], abstract="",
              categories=["astro-ph.HE"], published="2026-07-14",
              url="https://arxiv.org/abs/1")
    day = DayData(
        date="2026-07-14",
        review=DailyReview(date="2026-07-14", overview="new overview", highlights="", trends=""),
        items=[{"paper": p, "score": RelevanceScore(90, ["GRB"], "core", ""),
                "summary": PaperSummary("arxiv:1", "标题", "A 等", "t", "r", "h", "—")}],
        revisions=[{"synced": "2026-07-15", "n_papers": 1,
                    "review": {"date": "2026-07-14", "overview": "old overview",
                               "highlights": "", "trends": ""}}])
    st.save_day(day)
    out = tmp_path / "site"
    render_site(st, out, TEMPLATES, STATIC)
    page = (out / "day" / "2026-07-14.html").read_text(encoding="utf-8")
    assert "修订历史" in page
    assert "old overview" in page
    index = (out / "index.html").read_text(encoding="utf-8")
    assert "2026-07-14" in index   # as-of date shown on home


def test_render_home_skips_empty_latest_day(tmp_path):
    st = Store(tmp_path / "data")
    st.save_day(DayData(date="2026-07-17",
                        review=DailyReview("2026-07-17", "今日无新文献。", "—", "—"), items=[]))
    p = Paper(id="arxiv:1", source="arxiv", title="Real GRB", authors=["A"], abstract="",
              categories=["astro-ph.HE"], published="2026-07-16", url="https://arxiv.org/abs/1")
    st.save_day(DayData(date="2026-07-16",
                        review=DailyReview("2026-07-16", "16 概览", "", ""),
                        items=[{"paper": p, "score": RelevanceScore(90, ["GRB"], "core", ""),
                                "summary": PaperSummary("arxiv:1", "真实暴", "A 等", "t", "r", "h", "—")}]))
    out = tmp_path / "site"
    render_site(st, out, TEMPLATES, STATIC)
    index = (out / "index.html").read_text(encoding="utf-8")
    assert "真实暴" in index
    assert "今日无新文献" not in index
    assert "2026-07-16" in index
