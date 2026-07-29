from gdr.render import versions_for


def test_versions_for_lists_each_ingest_day_that_touched_this_archive_day(ritem):
    items = [ritem("arxiv:1", archive="2026-07-14", ingested="2026-07-18"),
             ritem("arxiv:2", archive="2026-07-14", ingested="2026-07-22"),
             ritem("arxiv:3", archive="2026-07-14", ingested="2026-07-22")]

    assert versions_for(items) == ["2026-07-18", "2026-07-22"]


def test_a_day_ingested_all_at_once_has_no_versions_to_switch_between(ritem):
    items = [ritem("arxiv:1", archive="2026-07-14", ingested="2026-07-18")]

    assert versions_for(items) == []


def test_historical_version_page_shows_only_what_was_known_then(
        ritem, build_site_from):
    out = build_site_from([
        ("2026-07-18", [ritem("arxiv:1", archive="2026-07-14",
                              ingested="2026-07-18")]),
        ("2026-07-22", [ritem("arxiv:2", archive="2026-07-14",
                              ingested="2026-07-22")])])

    latest = (out / "day" / "2026-07-14.html").read_text(encoding="utf-8")
    older = (out / "day" / "2026-07-14.as-of-2026-07-18.html").read_text(
        encoding="utf-8")

    assert "Title arxiv:1" in latest and "Title arxiv:2" in latest
    assert "Title arxiv:1" in older and "Title arxiv:2" not in older


def test_historical_version_carries_the_headline_as_it_stood_then(
        ritem, story_decision, build_site_from):
    out = build_site_from([
        ("2026-07-18", [ritem("arxiv:1", archive="2026-07-14",
                              ingested="2026-07-18")]),
        ("2026-07-22", [ritem("arxiv:2", archive="2026-07-14",
                              ingested="2026-07-22",
                              decision=story_decision("arxiv:2"))])])

    older = (out / "day" / "2026-07-14.as-of-2026-07-18.html").read_text(
        encoding="utf-8")
    latest = (out / "day" / "2026-07-14.html").read_text(encoding="utf-8")

    assert "头条 arxiv:2" in latest
    assert "头条 arxiv:2" not in older
    assert "今日无通过复核的重大进展" in older


def test_version_bar_links_every_version_and_marks_the_current_one(
        ritem, build_site_from):
    out = build_site_from([
        ("2026-07-18", [ritem("arxiv:1", archive="2026-07-14",
                              ingested="2026-07-18")]),
        ("2026-07-22", [ritem("arxiv:2", archive="2026-07-14",
                              ingested="2026-07-22")])])

    latest = (out / "day" / "2026-07-14.html").read_text(encoding="utf-8")

    assert 'class="version-bar"' in latest
    assert "2026-07-14.as-of-2026-07-18.html" in latest
    assert "最新" in latest


def test_version_bar_latest_link_shows_the_true_latest_count(
        ritem, build_site_from):
    """The 「最新」 link always points at the newest version, so its count must
    stay pinned to that version's paper total — not silently regress to
    whatever subset the page currently being viewed happens to show."""
    out = build_site_from([
        ("2026-07-18", [ritem("arxiv:1", archive="2026-07-14",
                              ingested="2026-07-18")]),
        ("2026-07-22", [ritem("arxiv:2", archive="2026-07-14",
                              ingested="2026-07-22")])])

    older = (out / "day" / "2026-07-14.as-of-2026-07-18.html").read_text(
        encoding="utf-8")

    assert "最新 · 2 篇" in older
    assert "最新 · 1 篇" not in older


def test_news_pages_have_no_version_bar(ritem, build_site_from):
    """An ingest day is immutable by construction — nothing to version."""
    out = build_site_from([("2026-07-18", [ritem("arxiv:1",
                                                 archive="2026-07-14",
                                                 ingested="2026-07-18")])])

    assert 'class="version-bar"' not in (
        out / "news" / "2026-07-18.html").read_text(encoding="utf-8")
