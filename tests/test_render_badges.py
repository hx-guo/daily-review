from gdr.render import archive_groups, backfill_batches, date_chain


def test_backfill_batches_exclude_the_first_ingest(ritem):
    items = [ritem("arxiv:1", archive="2026-07-14", ingested="2026-07-18"),
             ritem("arxiv:2", archive="2026-07-14", ingested="2026-07-22"),
             ritem("arxiv:3", archive="2026-07-14", ingested="2026-07-22")]

    assert backfill_batches(items) == [{"date": "2026-07-22", "n": 2}]


def test_no_batches_when_everything_arrived_together(ritem):
    assert backfill_batches([ritem("arxiv:1", archive="2026-07-14",
                                   ingested="2026-07-18")]) == []


def test_date_chain_omits_unknown_dates_and_keeps_month_precision(ritem):
    item = ritem("arxiv:1", archive="2026-03-14", ingested="2026-07-22")
    item["dates"].update({"preprint": "2026-03-14", "accepted": "",
                          "published": "2026-08", "published_precision": "month"})

    assert date_chain(item) == [{"label": "预印本", "value": "2026-03-14"},
                                {"label": "刊出", "value": "2026-08"},
                                {"label": "收录", "value": "2026-07-22"}]


def test_backfilled_cards_carry_a_badge_and_the_first_batch_does_not(
        ritem, build_site_from):
    out = build_site_from([
        ("2026-07-18", [ritem("arxiv:1", archive="2026-07-14",
                              ingested="2026-07-18")]),
        ("2026-07-22", [ritem("arxiv:2", archive="2026-07-14",
                              ingested="2026-07-22")])])

    page = (out / "day" / "2026-07-14.html").read_text(encoding="utf-8")

    assert page.count("backfill-badge") == 1
    assert "07-22 补录" in page
    assert "本页经 1 次补录" in page


def test_news_pages_have_no_backfill_badges(ritem, build_site_from):
    out = build_site_from([("2026-07-18", [ritem("arxiv:1",
                                                 archive="2026-07-14",
                                                 ingested="2026-07-18")])])

    assert "backfill-badge" not in (
        out / "news" / "2026-07-18.html").read_text(encoding="utf-8")


def test_archive_groups_by_year_month_newest_first(ritem, story_decision):
    items = {"2026-07-14": [ritem("arxiv:1", archive="2026-07-14",
                                  ingested="2026-07-18"),
                            ritem("arxiv:2", archive="2026-07-14",
                                  ingested="2026-07-22",
                                  decision=story_decision("arxiv:2",
                                                          "breaking"))],
             "2026-03-14": [ritem("arxiv:3", archive="2026-03-14",
                                  ingested="2026-07-22")]}

    groups = archive_groups(items)

    assert [g["ym"] for g in groups] == ["2026-07", "2026-03"]
    assert groups[0]["days"][0] == {"date": "2026-07-14", "n": 2,
                                    "breaking": True, "backfills": 1}
    assert groups[1]["days"][0]["breaking"] is False


def test_archive_page_marks_days_before_the_site_existed(ritem, build_site_from):
    out = build_site_from([("2026-07-22", [
        ritem("arxiv:1", archive="2026-03-14", ingested="2026-07-22"),
        ritem("arxiv:2", archive="2026-07-14", ingested="2026-07-22")])])

    page = (out / "archive.html").read_text(encoding="utf-8")

    assert "2026-03" in page
    assert "本站自 2026-07-12 起收录" in page
