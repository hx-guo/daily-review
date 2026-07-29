import json

from gdr.datesource import fetch_arxiv_v1_date, fetch_crossref_dates


class FakeResponse:
    def __init__(self, payload=None, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _crossref(message):
    calls = []

    def http_get(url, params=None, timeout=None):
        calls.append((url, params))
        return FakeResponse({"message": message})

    return http_get, calls


def test_crossref_reads_aas_iso_accepted_and_online_date():
    http_get, calls = _crossref({
        "published-online": {"date-parts": [[2026, 7, 3]]},
        "published-print": {"date-parts": [[2026, 7, 10]]},
        "created": {"date-parts": [[2026, 7, 3]]},
        "assertion": [{"name": "accepted", "value": "2026-05-23"},
                      {"name": "received", "value": "2026-02-16"}],
    })

    got = fetch_crossref_dates("10.3847/1538-4357/ae75dc", http_get=http_get)

    assert got == {"accepted": "2026-05-23", "published": "2026-07-03",
                   "published_precision": "day",
                   "published_source": "crossref-online", "received": "2026-02-16"}
    assert calls[0][0].endswith("/10.3847/1538-4357/ae75dc")


def test_crossref_reads_springer_english_long_form_accepted():
    http_get, _ = _crossref({
        "published-online": {"date-parts": [[2026, 7, 10]]},
        "assertion": [{"label": "Accepted", "value": "3 June 2026"},
                      {"label": "Received", "value": "9 January 2026"}],
    })

    got = fetch_crossref_dates("10.1038/s41550-026-02910-w", http_get=http_get)

    assert got["accepted"] == "2026-06-03"
    assert got["received"] == "2026-01-09"


def test_crossref_elsevier_scheduled_issue_falls_back_to_created():
    http_get, _ = _crossref({
        "published-print": {"date-parts": [[2026, 8]]},
        "created": {"date-parts": [[2026, 7, 6]]},
    })

    got = fetch_crossref_dates("10.1016/j.jheap.2026.100692", http_get=http_get)

    assert got["published"] == "2026-07-06"
    assert got["published_source"] == "crossref-created"
    assert got["accepted"] == ""


def test_crossref_aps_gives_received_but_no_accepted():
    http_get, _ = _crossref({
        "published-online": {"date-parts": [[2026, 7, 7]]},
        "assertion": [{"name": "received", "value": "2026-03-19"}],
    })

    got = fetch_crossref_dates("10.1103/v7dk-q18l", http_get=http_get)

    assert got["accepted"] == ""
    assert got["received"] == "2026-03-19"


def test_crossref_failures_return_empty_dict_rather_than_raising():
    def boom(url, params=None, timeout=None):
        raise RuntimeError("network down")

    assert fetch_crossref_dates("10.1/x", http_get=boom) == {}
    assert fetch_crossref_dates("", http_get=boom) == {}
    assert fetch_crossref_dates(
        "10.1/x", http_get=lambda *a, **k: FakeResponse(status_code=404)) == {}


ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2603.09495v2</id>
    <published>2026-03-12T17:59:59Z</published>
    <updated>2026-06-01T10:00:00Z</updated>
    <title>A paper</title>
    <summary>abstract</summary>
  </entry>
</feed>"""


def test_arxiv_v1_date_is_the_published_field_not_updated():
    def http_get(url, params=None, timeout=None):
        assert params["id_list"] == "2603.09495"
        return FakeResponse(text=ATOM)

    assert fetch_arxiv_v1_date("2603.09495", http_get=http_get) == "2026-03-12"


def test_arxiv_v1_date_empty_on_failure():
    def boom(url, params=None, timeout=None):
        raise RuntimeError("network down")

    assert fetch_arxiv_v1_date("2603.09495", http_get=boom) == ""
    assert fetch_arxiv_v1_date("", http_get=boom) == ""
