from gdr.dates import archive_date, earliest, parse_partial_date, pick_published, sort_value


def test_parse_iso_day_month_and_year():
    assert parse_partial_date("2026-05-23") == ("2026-05-23", "day")
    assert parse_partial_date("2026-07") == ("2026-07", "month")
    assert parse_partial_date("2026") == ("2026", "year")


def test_parse_ads_zero_day_is_month_precision():
    """ADS pubdate writes an unknown day as 00; it must never become a real day."""
    assert parse_partial_date("2026-07-00") == ("2026-07", "month")


def test_parse_crossref_date_parts():
    assert parse_partial_date([[2026, 7, 8]]) == ("2026-07-08", "day")
    assert parse_partial_date([2026, 9]) == ("2026-09", "month")


def test_parse_english_long_form_used_by_springer_and_pleiades():
    assert parse_partial_date("3 June 2026") == ("2026-06-03", "day")
    assert parse_partial_date("26 May 2026") == ("2026-05-26", "day")
    assert parse_partial_date("January 9, 2026") == ("2026-01-09", "day")


def test_unparseable_input_yields_empty_rather_than_a_guess():
    for junk in ("", None, "in press", "n.d.", [], [[]]):
        assert parse_partial_date(junk) == ("", "")


def test_sort_value_pads_coarse_precision():
    assert sort_value("2026-07") == "2026-07-01"
    assert sort_value("2026") == "2026-01-01"
    assert sort_value("2026-07-08") == "2026-07-08"
    assert sort_value("") == ""


def test_earliest_ignores_blanks_and_keeps_original_precision():
    assert earliest("", "2026-07", "2026-07-08") == "2026-07"
    assert earliest("", "") == ""


def test_pick_published_prefers_online():
    got = pick_published(online=[[2026, 7, 3]], printed=[[2026, 7, 10]],
                         created=[[2026, 7, 3]])
    assert got == {"date": "2026-07-03", "precision": "day",
                   "source": "crossref-online"}


def test_pick_published_rejects_elsevier_future_issue_date():
    """Elsevier deposits a scheduled issue month later than the real online date."""
    got = pick_published(online=None, printed=[[2026, 8]], created=[[2026, 7, 6]])
    assert got == {"date": "2026-07-06", "precision": "day",
                   "source": "crossref-created"}


def test_pick_published_keeps_print_when_not_in_the_future():
    got = pick_published(online=None, printed=[[2026, 4, 24]], created=[[2026, 5, 2]])
    assert got == {"date": "2026-04-24", "precision": "day",
                   "source": "crossref-print"}


def test_pick_published_falls_back_to_ads_pubdate():
    got = pick_published(ads_pubdate="2026-07-00")
    assert got == {"date": "2026-07", "precision": "month", "source": "ads-pubdate"}


def test_pick_published_with_nothing_known():
    assert pick_published() == {"date": "", "precision": "", "source": ""}


def test_archive_date_is_the_earliest_academic_date_at_day_precision():
    dates = {"preprint": "2026-03-14", "accepted": "2026-06-21",
             "published": "2026-07-08", "ingested": "2026-07-22"}
    assert archive_date(dates) == "2026-03-14"


def test_archive_date_ignores_ingested_and_pads_month_precision():
    assert archive_date({"preprint": "", "accepted": "",
                         "published": "2026-07", "ingested": "2026-07-22"}) == "2026-07-01"


def test_archive_date_empty_when_no_academic_date_is_known():
    assert archive_date({"ingested": "2026-07-22"}) == ""
