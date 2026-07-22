import re
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
    # journal masthead + roman-numeral sections
    assert "HIGH-ENERGY TRANSIENTS" in index
    assert 'class="masthead"' in index
    assert "当日总览" in index and "核心文献" in index
    # core sorts before related
    assert index.index("核心文章") < index.index("相关文章")
    assert (out / "day" / "2026-07-18.html").exists()
    assert (out / "archive.html").exists()
    assert (out / "static" / "style.css").exists()
    assert (out / "static" / "fonts" / "fonts.css").exists()
    assert 'href="static/fonts/fonts.css"' in index
    assert "fonts.googleapis.com" not in index
    assert "fonts.gstatic.com" not in index
    font_css = (out / "static" / "fonts" / "fonts.css").read_text(encoding="utf-8")
    assert "https://" not in font_css
    font_files = re.findall(r"url\('\./([^']+\.woff2)'\)", font_css)
    assert font_files
    assert all((out / "static" / "fonts" / name).exists() for name in font_files)


def test_render_equal_news_stories_without_a_lead(tmp_path):
    st = Store(tmp_path / "data")
    review = DailyReview(
        date="2026-07-18", overview="有重大进展。", highlights="", trends="",
        editorial_version=2,
        stories=[
            {"paper_id": "arxiv:2607.1", "level": "breaking", "title": "磁星爆发",
             "evidence": "探测到高能对应体", "impact": "约束爆发区尺度", "reason": "首次观测"},
            {"paper_id": "arxiv:2607.2", "level": "breaking", "title": "另一项重大进展",
             "evidence": "独立探测到新信号", "impact": "改变辐射模型", "reason": "突破结果"},
        ],
        watchlist=["等待第二台仪器独立确认"],
    )
    st.save_day(DayData("2026-07-18", review,
                        [_item("arxiv:2607.1", 98, "core", "磁星爆发"),
                         _item("arxiv:2607.2", 97, "core", "另一项重大进展")]))
    out = tmp_path / "site"
    render_site(st, out, TEMPLATES, STATIC)
    page = (out / "index.html").read_text(encoding="utf-8")
    assert "今日头条" in page
    assert "BREAKING · 突发" in page
    assert "磁星爆发" in page and "另一项重大进展" in page
    assert page.count('class="news-story breaking"') == 2
    assert "主头条" not in page
    assert "继续观察" in page
    assert 'href="#paper-arxiv-2607-1"' in page


def test_render_ads_paper_shows_ads_doi_and_arxiv_links(tmp_path):
    st = Store(tmp_path / "data")
    p = Paper(
        id="ads:2026ApJ...999...1A", source="ads", title="Published transient",
        authors=["A"], abstract="abs", categories=["Gamma-ray bursts"],
        published="2026-07-18",
        url="https://ui.adsabs.harvard.edu/abs/2026ApJ...999...1A/abstract",
        doi="10.1234/example", external_ids={
            "ads": "2026ApJ...999...1A", "arxiv": "2607.00001", "doi": "10.1234/example"
        },
    )
    day = DayData(
        "2026-07-18", DailyReview("2026-07-18", "o", "", ""),
        items=[{"paper": p, "score": RelevanceScore(90, ["GRB"], "core", ""),
                "summary": PaperSummary(p.id, "正式发表论文", "", "", "", "", "")}],
    )
    st.save_day(day)
    out = tmp_path / "site"
    render_site(st, out, TEMPLATES, STATIC)
    page = (out / "day" / "2026-07-18.html").read_text(encoding="utf-8")
    assert "ADS:2026ApJ...999...1A" in page
    assert "https://doi.org/10.1234/example" in page
    assert "https://arxiv.org/abs/2607.00001" in page
    assert "元数据来自 arXiv 与 NASA ADS" in page


def test_render_masthead_meta(tmp_path):
    st = Store(tmp_path / "data")
    st.save_day(DayData(date="2026-07-16",
                        review=DailyReview("2026-07-16", "o", "", ""),
                        items=[_item("c", 90, "core", "核心一")]))
    out = tmp_path / "site"
    render_site(st, out, TEMPLATES, STATIC)
    page = (out / "day" / "2026-07-16.html").read_text(encoding="utf-8")
    # volume = year, issue no. = day-of-year (2026-07-16 is day 197), Chinese weekday
    assert "Vol. 2026 · No. 197" in page
    assert "2026 年 7 月 16 日" in page
    assert "星期四" in page
    # header roll-up count: core + related, with per-layer breakdown
    assert "收录 1 篇" in page
    assert "核心 1 · 相关 0 · 边缘 0" in page


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
    # the removed-on-purpose per-card block must not reappear
    assert "与我们的关联" not in page


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
    assert "2026 年 7 月 14 日" in index   # as-of date shown on home (Chinese masthead date)


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
    assert "2026 年 7 月 16 日" in index


def test_render_edge_collapsed_with_chinese(tmp_path):
    st = Store(tmp_path / "data")
    core_p = Paper(id="arxiv:c", source="arxiv", title="Core Eng", authors=["A"], abstract="",
                   categories=["astro-ph.HE"], published="2026-07-16", url="https://arxiv.org/abs/c")
    edge_p = Paper(id="arxiv:e", source="arxiv", title="Edge English Title", authors=["Bailey B"],
                   abstract="eng abs", categories=["astro-ph.HE"], published="2026-07-16",
                   url="https://arxiv.org/abs/e")
    day = DayData(date="2026-07-16",
                  review=DailyReview("2026-07-16", "概览", "", ""),
                  items=[{"paper": core_p, "score": RelevanceScore(90, ["GRB"], "core", ""),
                          "summary": PaperSummary("arxiv:c", "核心中文", "A 等", "t", "r", "h", "—")},
                         {"paper": edge_p, "score": RelevanceScore(20, [], "edge", ""),
                          "summary": PaperSummary("arxiv:e", "边缘中文标题", "", "边缘一句话", "", "", "")}])
    st.save_day(day)
    out = tmp_path / "site"
    render_site(st, out, TEMPLATES, STATIC)
    page = (out / "day" / "2026-07-16.html").read_text(encoding="utf-8")
    assert "核心中文" in page
    assert "边缘中文标题" in page
    assert "Bailey B" in page                  # edge cards still show author names
    assert "<details" in page
    assert "边缘相关" in page


def test_render_english_original_block(tmp_path):
    st = Store(tmp_path / "data")
    p = Paper(id="arxiv:1", source="arxiv", title="A GRB Study",
              authors=["Alice A", "Bob B", "Cara C", "Dan D"],
              abstract="Full English abstract text here.", categories=["astro-ph.HE"],
              published="2026-07-16", url="https://arxiv.org/abs/1")
    summ = PaperSummary("arxiv:1", "中文标题", "团队", "tl", "综述", "亮点", "关联",
                        authors_en="Alice A (MIT), Bob B (Caltech), Cara C (IHEP), et al.",
                        corresponding_en="Alice A")
    day = DayData("2026-07-16", DailyReview("2026-07-16", "o", "", ""),
                  items=[{"paper": p, "score": RelevanceScore(90, ["GRB"], "core", ""), "summary": summ}])
    st.save_day(day)
    out = tmp_path / "site"
    render_site(st, out, TEMPLATES, STATIC)
    page = (out / "day" / "2026-07-16.html").read_text(encoding="utf-8")
    assert "A GRB Study" in page
    assert page.count("A GRB Study") == 1   # english title shown once
    assert "Alice A" in page
    assert 'class="affil">(MIT)' in page     # affiliation styled as a lighter parenthetical
    assert "✉" in page and "corr-mark" in page   # corresponding-author envelope
    assert 'class="etal">et al.' in page          # et al. italicised (Latin only)
    assert "Full English abstract text here." in page
    assert "abstract clamped" in page
    assert "abstract-toggle" in page
    # AI review zone: 亮点 (highlight) + 脉络与展望 (review), 以原文为准 caption
    assert "AI 综述" in page
    assert "亮点" in page and "脉络与展望" in page
    assert "以原文为准" in page
    # Chinese translated title present (below the English original), no old label
    assert "中文标题" in page
    assert "中文标题：" not in page
    assert (out / "static" / "search.js").exists()


def test_render_context_outlook_citation_chips(tmp_path):
    st = Store(tmp_path / "data")
    p = Paper(id="arxiv:1", source="arxiv", title="T", authors=["A"], abstract="abs",
              categories=["astro-ph.HE"], published="2026-07-16", url="https://arxiv.org/abs/1")
    summ = PaperSummary("arxiv:1", "中文", "", "", "", "亮点在此", "",
                        context_outlook="承接 [[DeLaunay+ 2022]] 与 [[Wijnands+ 2013]]，展望多信使。",
                        citations=[  # resolved: DeLaunay has a verified ADS/arXiv url; Wijnands unresolved
                            {"label": "DeLaunay+ 2022", "url": "https://arxiv.org/abs/2205.01346",
                             "source": "ads", "verified": True, "ref": "DeLaunay et al. 2022"},
                            {"label": "Wijnands+ 2013", "url": "", "source": "", "verified": False,
                             "ref": "Wijnands et al. 2013 MNRAS 432 2366"}])
    day = DayData("2026-07-16", DailyReview("2026-07-16", "o", "", ""),
                  items=[{"paper": p, "score": RelevanceScore(90, [], "core", ""), "summary": summ}])
    st.save_day(day)
    out = tmp_path / "site"; render_site(st, out, TEMPLATES, STATIC)
    page = (out / "day" / "2026-07-16.html").read_text(encoding="utf-8")
    assert "脉络与展望" in page
    # inline [[markers]] become linked chips, not raw brackets
    assert "[[" not in page and "]]" not in page
    assert 'class="cite"' in page
    assert 'href="https://arxiv.org/abs/2205.01346"' in page       # resolved -> direct link
    # unresolved -> ADS search of the reference string (not a guessed specific paper)
    assert "ui.adsabs.harvard.edu/search/q=Wijnands" in page
    assert ">DeLaunay+ 2022</a>" in page and ">Wijnands+ 2013</a>" in page


def test_render_et_al_when_authors_truncated(tmp_path):
    st = Store(tmp_path / "data")
    p = Paper(id="arxiv:1", source="arxiv", title="T",
              authors=["A one", "B two", "C three", "D four", "E five"], abstract="abs",
              categories=["astro-ph.HE"], published="2026-07-16", url="https://arxiv.org/abs/1")
    # authors_en empty -> falls back to first 3 names, must append et al. (5 > 3)
    summ = PaperSummary("arxiv:1", "中文", "", "", "", "", "")
    day = DayData("2026-07-16", DailyReview("2026-07-16", "o", "", ""),
                  items=[{"paper": p, "score": RelevanceScore(90, [], "core", ""), "summary": summ}])
    st.save_day(day)
    out = tmp_path / "site"; render_site(st, out, TEMPLATES, STATIC)
    page = (out / "day" / "2026-07-16.html").read_text(encoding="utf-8")
    assert "et al." in page


def test_render_toc_drawer_and_section_anchors(tmp_path):
    st = Store(tmp_path / "data")
    core = Paper(id="arxiv:c1", source="arxiv", title="Core One", authors=["A"], abstract="",
                 categories=["astro-ph.HE"], published="2026-07-16", url="https://arxiv.org/abs/c1")
    rel = Paper(id="arxiv:r1", source="arxiv", title="Rel One", authors=["B"], abstract="",
                categories=["astro-ph.HE"], published="2026-07-16", url="https://arxiv.org/abs/r1")
    day = DayData("2026-07-16", DailyReview("2026-07-16", "o", "", ""), items=[
        {"paper": core, "score": RelevanceScore(90, ["GRB"], "core", ""),
         "summary": PaperSummary("arxiv:c1", "核心一", "", "", "", "", "")},
        {"paper": rel, "score": RelevanceScore(50, [], "related", ""),
         "summary": PaperSummary("arxiv:r1", "相关一", "", "", "", "", "")}])
    st.save_day(day)
    out = tmp_path / "site"
    render_site(st, out, TEMPLATES, STATIC)
    page = (out / "day" / "2026-07-16.html").read_text(encoding="utf-8")
    assert "toc-drawer" in page and "toc-tab" in page   # collapsible left-margin drawer
    assert 'href="#overview"' in page
    assert 'href="#paper-arxiv-c1"' in page      # per-paper jump link
    assert 'id="paper-arxiv-c1"' in page          # matching anchor on the card
    assert 'id="overview"' in page and 'id="core"' in page and 'id="related"' in page
    # section headings use roman numerals
    assert "核心文献" in page and "相关文献" in page
