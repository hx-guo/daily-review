import re
from pathlib import Path

from gdr.models import IngestDay, Paper, PaperSummary, RelevanceScore, make_item
from gdr.render import group_by, render_site, split_watch
from gdr.store import Store

TEMPLATES = Path(__file__).parent.parent / "templates"
STATIC = Path(__file__).parent.parent / "static"


def test_group_by_archive_and_ingest_are_independent_groupings(ritem):
    items = [ritem("arxiv:1", archive="2026-07-14", ingested="2026-07-18"),
             ritem("arxiv:2", archive="2026-07-14", ingested="2026-07-22")]

    assert sorted(group_by(items, "archive")) == ["2026-07-14"]
    assert sorted(group_by(items, "ingest")) == ["2026-07-18", "2026-07-22"]


def test_site_has_one_news_page_per_ingest_day_and_one_day_page_per_archive_day(
        ritem, build_site_from):
    out = build_site_from([
        ("2026-07-18", [ritem("arxiv:1", archive="2026-07-14",
                              ingested="2026-07-18")]),
        ("2026-07-22", [ritem("arxiv:2", archive="2026-07-14",
                              ingested="2026-07-22"),
                        ritem("arxiv:3", archive="2026-07-20",
                              ingested="2026-07-22")])])

    assert (out / "news" / "2026-07-18.html").exists()
    assert (out / "news" / "2026-07-22.html").exists()
    assert (out / "day" / "2026-07-14.html").exists()
    assert (out / "day" / "2026-07-20.html").exists()


def test_home_page_is_the_latest_ingest_day(ritem, build_site_from):
    out = build_site_from([
        ("2026-07-18", [ritem("arxiv:1", archive="2026-07-14",
                              ingested="2026-07-18")]),
        ("2026-07-22", [ritem("arxiv:2", archive="2026-07-20",
                              ingested="2026-07-22")])])

    home = (out / "index.html").read_text(encoding="utf-8")

    assert "Title arxiv:2" in home
    assert "Title arxiv:1" not in home
    assert "本日收录" in home


def test_news_pages_link_to_their_neighbouring_ingest_days(ritem, build_site_from):
    """Without this the news axis is unreachable: nothing else on the site links
    to news/*.html, so every page but the newest would need its URL typed."""
    out = build_site_from([
        ("2026-07-18", [ritem("arxiv:1", archive="2026-07-18",
                              ingested="2026-07-18")]),
        ("2026-07-22", [ritem("arxiv:2", archive="2026-07-22",
                              ingested="2026-07-22")])])

    newest = (out / "news" / "2026-07-22.html").read_text(encoding="utf-8")
    oldest = (out / "news" / "2026-07-18.html").read_text(encoding="utf-8")
    home = (out / "index.html").read_text(encoding="utf-8")
    archive = (out / "day" / "2026-07-22.html").read_text(encoding="utf-8")

    assert 'href="../news/2026-07-18.html"' in newest and "前一收录日" in newest
    assert 'href="news/2026-07-18.html"' in home        # the home page is a news page
    assert "前一收录日" not in oldest                    # nothing precedes the oldest day
    assert 'href="../news/2026-07-22.html"' in oldest and "后一收录日" in oldest
    assert 'class="news-nav"' not in archive             # news axis only


def test_archive_page_shows_every_paper_of_that_archive_day_whenever_ingested(
        ritem, build_site_from):
    out = build_site_from([
        ("2026-07-18", [ritem("arxiv:1", archive="2026-07-14",
                              ingested="2026-07-18")]),
        ("2026-07-22", [ritem("arxiv:2", archive="2026-07-14",
                              ingested="2026-07-22")])])

    page = (out / "day" / "2026-07-14.html").read_text(encoding="utf-8")

    assert "Title arxiv:1" in page and "Title arxiv:2" in page
    assert "最早日期为此日" in page


def test_stories_render_on_both_axes_from_the_same_decision(
        ritem, story_decision, build_site_from):
    item = ritem("arxiv:1", archive="2026-07-14", ingested="2026-07-18",
                 decision=story_decision("arxiv:1"))
    out = build_site_from([("2026-07-18", [item])])

    news = (out / "news" / "2026-07-18.html").read_text(encoding="utf-8")
    archive = (out / "day" / "2026-07-14.html").read_text(encoding="utf-8")

    for page in (news, archive):
        assert "头条 arxiv:1" in page
        assert "影响" in page


def test_render_site(ritem, build_site_from):
    items = [ritem("rel1", archive="2026-07-18", ingested="2026-07-18",
                   layer="related", score=50),
             ritem("core1", archive="2026-07-18", ingested="2026-07-18",
                   layer="core", score=95)]
    out = build_site_from([("2026-07-18", items)])

    index = (out / "index.html").read_text(encoding="utf-8")
    # journal masthead + roman-numeral sections
    assert "HIGH-ENERGY TRANSIENTS" in index
    assert 'class="masthead"' in index
    assert "今日头条" in index and "核心文献" in index
    # core sorts before related
    assert index.index("中文 core1") < index.index("中文 rel1")
    assert (out / "day" / "2026-07-18.html").exists()
    assert (out / "news" / "2026-07-18.html").exists()
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


def test_render_equal_news_stories_without_a_lead(ritem, build_site_from):
    item1 = ritem("arxiv:2607.1", archive="2026-07-18", ingested="2026-07-18", score=98,
                 decision={"level": "breaking", "title": "磁星爆发",
                           "evidence": "探测到高能对应体", "impact": "约束爆发区尺度",
                           "reason": "首次观测", "watchlist": ["等待第二台仪器独立确认"],
                           "reviewed_at": "2026-07-18"})
    item2 = ritem("arxiv:2607.2", archive="2026-07-18", ingested="2026-07-18", score=97,
                 decision={"level": "breaking", "title": "另一项重大进展",
                           "evidence": "独立探测到新信号", "impact": "改变辐射模型",
                           "reason": "突破结果", "watchlist": [],
                           "reviewed_at": "2026-07-18"})
    out = build_site_from([("2026-07-18", [item1, item2])])
    page = (out / "index.html").read_text(encoding="utf-8")
    assert "今日头条" in page
    assert "BREAKING · 突发" in page
    assert "磁星爆发" in page and "另一项重大进展" in page
    # breaking always gets the full treatment
    assert page.count('class="story breaking"') == 2
    assert "主头条" not in page
    assert "继 续 观 察" in page
    assert 'href="#paper-arxiv-2607-1"' in page
    # impact is the unlabelled payload; evidence is labelled support; reason stays collapsed
    assert 'class="story-impact">约束爆发区尺度' in page
    assert "证据" in page and "探测到高能对应体" in page
    assert "入选依据 ▾" in page and "<details" in page


def _story_items(ritem, n_breaking, n_headline, date):
    items = [ritem(f"arxiv:b{i}", archive=date, ingested=date, score=95,
                   decision={"level": "breaking", "title": f"突发{i}",
                             "evidence": f"证据{i}", "impact": f"影响{i}",
                             "reason": f"依据{i}", "watchlist": [], "reviewed_at": date})
             for i in range(n_breaking)]
    items += [ritem(f"arxiv:h{i}", archive=date, ingested=date, score=90,
                    decision={"level": "headline", "title": f"头条{i}",
                              "evidence": f"证据h{i}", "impact": f"影响h{i}",
                              "reason": f"依据h{i}", "watchlist": [], "reviewed_at": date})
              for i in range(n_headline)]
    return items


def test_render_heavy_day_tiers_headline_stories(ritem, build_site_from):
    """A heavy day must never print ten full-treatment stories: breaking stays full,
    every headline drops to the compact ranked row when a breaking exists."""
    items = _story_items(ritem, 2, 8, "2026-07-19")
    out = build_site_from([("2026-07-19", items)])
    page = (out / "day" / "2026-07-19.html").read_text(encoding="utf-8")
    assert "10 条 · 含 2 突发" in page
    assert page.count('class="story breaking"') == 2
    assert page.count('class="story-lite headline"') == 8
    assert 'class="story headline"' not in page
    assert "证据与入选依据 ▾" in page          # merged fold on compact rows
    # sequence numerals run continuously across both tiers
    assert ">01<" in page and ">10<" in page


def test_render_light_day_gives_first_two_headlines_full_treatment(ritem, build_site_from):
    items = _story_items(ritem, 0, 4, "2026-07-21")
    out = build_site_from([("2026-07-21", items)])
    page = (out / "day" / "2026-07-21.html").read_text(encoding="utf-8")
    assert "4 条 · 无突发" in page
    assert "BREAKING" not in page
    assert page.count('class="story headline"') == 2
    assert page.count('class="story-lite headline"') == 2


def test_render_empty_headline_day_shows_notice(ritem, build_site_from):
    items = [ritem(f"arxiv:{i}", archive="2026-07-20", ingested="2026-07-20", score=90,
                   decision={"level": "reject", "title": "", "evidence": "", "impact": "",
                             "reason": "常规推进", "watchlist": [],
                             "reviewed_at": "2026-07-20"})
             for i in range(5)]
    out = build_site_from([("2026-07-20", items)])
    page = (out / "day" / "2026-07-20.html").read_text(encoding="utf-8")
    assert 'class="hl-empty"' in page
    assert "今日无通过复核的重大进展" in page
    assert "均为常规推进" in page
    assert "No Breaking · 无突发" in page
    assert 'class="hl-count">无' in page


def test_render_watchlist_signal_renders_as_cite_link(ritem, build_site_from):
    # watchlist entries only surface for retained (non-reject) stories, so this
    # exercises the id-extraction/link rendering alongside a real headline.
    item = ritem("arxiv:1", archive="2026-07-22", ingested="2026-07-22", score=90,
                decision={"level": "headline", "title": "头条", "evidence": "证据",
                          "impact": "影响", "reason": "依据",
                          "watchlist": ["arxiv:2607.19298 预言的奇异星 kHz 引力波回波"
                                       "频率需后续观测验证"],
                          "reviewed_at": "2026-07-22"})
    out = build_site_from([("2026-07-22", [item])])
    page = (out / "day" / "2026-07-22.html").read_text(encoding="utf-8")
    assert "继 续 观 察" in page
    assert 'class="watch-id"' in page
    assert 'href="https://arxiv.org/abs/2607.19298"' in page
    assert "预言的奇异星 kHz 引力波回波频率需后续观测验证" in page


def test_split_watch_pulls_leading_arxiv_id():
    w = split_watch("arxiv:2607.19298 预言的奇异星 kHz 引力波回波频率需后续观测验证")
    assert w["label"] == "arXiv:2607.19298"
    assert w["url"] == "https://arxiv.org/abs/2607.19298"
    assert w["text"] == "预言的奇异星 kHz 引力波回波频率需后续观测验证"


def test_split_watch_pulls_trailing_parenthesised_ads_id():
    w = split_watch("GRB 231126A：最接近的 GRB-GW 关联候选，尚需独立后随观测确认"
                    "（ads:2026ApJ..1006...56A）")
    assert w["label"] == "ADS 2026ApJ..1006...56A"
    assert w["url"] == "https://ui.adsabs.harvard.edu/abs/2026ApJ..1006...56A"
    assert w["text"] == "GRB 231126A：最接近的 GRB-GW 关联候选，尚需独立后随观测确认"


def test_split_watch_without_id_keeps_text_verbatim():
    assert split_watch("等待第二台仪器独立确认") == {
        "label": "", "url": "", "text": "等待第二台仪器独立确认"}


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
    item = make_item(p, RelevanceScore(90, ["GRB"], "core", ""),
                     PaperSummary(p.id, "正式发表论文", "", "", "", "", ""),
                     dates={"preprint": "2026-07-18", "ingested": "2026-07-18"})
    st.save_ingest(IngestDay(ingested="2026-07-18", items=[item]))
    out = tmp_path / "site"
    render_site(st, out, TEMPLATES, STATIC)
    page = (out / "day" / "2026-07-18.html").read_text(encoding="utf-8")
    assert "ADS:2026ApJ...999...1A" in page
    assert "https://doi.org/10.1234/example" in page
    assert "https://arxiv.org/abs/2607.00001" in page
    assert "元数据来自 arXiv 与 NASA ADS" in page


def test_render_masthead_meta(ritem, build_site_from):
    items = [ritem("c", archive="2026-07-16", ingested="2026-07-16",
                   layer="core", score=90)]
    out = build_site_from([("2026-07-16", items)])
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
              abstract="edge abstract text", categories=["astro-ph.HE"],
              published="2026-07-18", url="https://arxiv.org/abs/e1")
    item = make_item(p, RelevanceScore(score=10, tags=[], layer="edge", reason=""), None,
                     dates={"preprint": "2026-07-18", "ingested": "2026-07-18"})
    st.save_ingest(IngestDay(ingested="2026-07-18", items=[item]))
    out = tmp_path / "site"
    render_site(st, out, TEMPLATES, STATIC)
    page = (out / "day" / "2026-07-18.html").read_text(encoding="utf-8")
    assert "Edge Paper Title" in page
    assert "edge abstract text" in page
    assert "TL;DR：" not in page
    # the removed-on-purpose per-card block must not reappear
    assert "与我们的关联" not in page


def test_render_home_skips_empty_latest_day(ritem, build_site_from):
    out = build_site_from([
        ("2026-07-16", [ritem("arxiv:1", archive="2026-07-16", ingested="2026-07-16",
                              layer="core", score=90)]),
        ("2026-07-17", []),
    ])
    index = (out / "index.html").read_text(encoding="utf-8")
    assert "Title arxiv:1" in index
    assert "2026 年 7 月 16 日" in index
    # an ingest day with no items never becomes a news page or the home page
    assert not (out / "news" / "2026-07-17.html").exists()


def test_render_edge_collapsed_with_chinese(tmp_path):
    st = Store(tmp_path / "data")
    core_p = Paper(id="arxiv:c", source="arxiv", title="Core Eng", authors=["A"],
                   abstract="", categories=["astro-ph.HE"], published="2026-07-16",
                   url="https://arxiv.org/abs/c")
    edge_p = Paper(id="arxiv:e", source="arxiv", title="Edge English Title",
                   authors=["Bailey B"], abstract="eng abs",
                   categories=["astro-ph.HE"], published="2026-07-16",
                   url="https://arxiv.org/abs/e")
    dates = {"preprint": "2026-07-16", "ingested": "2026-07-16"}
    items = [
        make_item(core_p, RelevanceScore(90, ["GRB"], "core", ""),
                 PaperSummary("arxiv:c", "核心中文", "A 等", "t", "r", "h", "—"),
                 dates=dates),
        make_item(edge_p, RelevanceScore(20, [], "edge", ""),
                 PaperSummary("arxiv:e", "边缘中文标题", "", "边缘一句话", "", "", ""),
                 dates=dates),
    ]
    st.save_ingest(IngestDay(ingested="2026-07-16", items=items))
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
    item = make_item(p, RelevanceScore(90, ["GRB"], "core", ""), summ,
                     dates={"preprint": "2026-07-16", "ingested": "2026-07-16"})
    st.save_ingest(IngestDay(ingested="2026-07-16", items=[item]))
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
    item = make_item(p, RelevanceScore(90, [], "core", ""), summ,
                     dates={"preprint": "2026-07-16", "ingested": "2026-07-16"})
    st.save_ingest(IngestDay(ingested="2026-07-16", items=[item]))
    out = tmp_path / "site"
    render_site(st, out, TEMPLATES, STATIC)
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
    item = make_item(p, RelevanceScore(90, [], "core", ""), summ,
                     dates={"preprint": "2026-07-16", "ingested": "2026-07-16"})
    st.save_ingest(IngestDay(ingested="2026-07-16", items=[item]))
    out = tmp_path / "site"
    render_site(st, out, TEMPLATES, STATIC)
    page = (out / "day" / "2026-07-16.html").read_text(encoding="utf-8")
    assert "et al." in page


def test_render_toc_drawer_and_section_anchors(ritem, build_site_from):
    items = [ritem("arxiv:c1", archive="2026-07-16", ingested="2026-07-16",
                   layer="core", score=90),
             ritem("arxiv:r1", archive="2026-07-16", ingested="2026-07-16",
                   layer="related", score=50)]
    out = build_site_from([("2026-07-16", items)])
    page = (out / "day" / "2026-07-16.html").read_text(encoding="utf-8")
    assert "toc-drawer" in page and "toc-tab" in page   # collapsible left-margin drawer
    assert 'href="#overview"' in page
    assert 'href="#paper-arxiv-c1"' in page      # per-paper jump link
    assert 'id="paper-arxiv-c1"' in page          # matching anchor on the card
    assert 'id="overview"' in page and 'id="core"' in page and 'id="related"' in page
    # section headings use roman numerals
    assert "核心文献" in page and "相关文献" in page
