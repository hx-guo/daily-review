from gdr.sources.ads_source import ADSSource, doc_to_paper


def _doc(n=1, *, entdate="2026-07-18"):
    return {
        "bibcode": f"2026ApJ...999...{n}A",
        "title": [f"A GECAM gamma-ray burst study {n}"],
        "author": ["Author, Alice", "Boss, Bob"],
        "abstract": "We report a transient.",
        "keyword": ["Gamma-ray bursts"],
        "arxiv_class": ["astro-ph.HE"],
        "entdate": entdate,
        "date": "2026-07-01T00:00:00.000Z",
        "doi": ["10.48550/arXiv.2607.00001", f"10.1234/example.{n}"],
        "identifier": [f"arXiv:2607.0000{n}"],
    }


class _Resp:
    def __init__(self, docs, total=None, status=200):
        self.status_code = status
        self._payload = {"response": {"docs": docs, "numFound": len(docs) if total is None else total}}

    def json(self):
        return self._payload


def test_doc_to_paper_maps_ads_metadata_and_identifiers():
    p = doc_to_paper(_doc())
    assert p.id == "ads:2026ApJ...999...1A"
    assert p.source == "ads"
    assert p.title == "A GECAM gamma-ray burst study 1"
    assert p.authors == ["Author, Alice", "Boss, Bob"]
    assert p.published == "2026-07-18"  # ADS entry day, not month-only publication day
    assert p.doi == "10.1234/example.1"
    assert p.external_ids == {
        "ads": "2026ApJ...999...1A",
        "arxiv": "2607.00001",
        "doi": "10.1234/example.1",
    }
    assert p.pdf_url == "https://arxiv.org/pdf/2607.00001"


def test_fetch_recent_queries_entry_window_with_bearer_token_and_paginates():
    calls = []

    def fake_get(url, headers=None, params=None, timeout=None):
        calls.append((url, headers, dict(params)))
        if params["start"] == 0:
            return _Resp([_doc(1), _doc(2)], total=3)
        return _Resp([_doc(3)], total=3)

    src = ADSSource("secret", query="property:refereed", http_get=fake_get,
                    page_size=2, request_delay=0)
    got = src.fetch_recent("2026-07-18", 3)
    assert [p.id for p in got] == [
        "ads:2026ApJ...999...1A",
        "ads:2026ApJ...999...2A",
        "ads:2026ApJ...999...3A",
    ]
    assert calls[0][1] == {"Authorization": "Bearer secret"}
    assert "entdate:[2026-07-16 TO 2026-07-18]" in calls[0][2]["q"]
    assert [call[2]["start"] for call in calls] == [0, 2]


def test_fetch_recent_missing_token_is_disabled_without_http_call():
    def fail(*args, **kwargs):
        raise AssertionError("HTTP must not be called without a token")

    assert ADSSource("", http_get=fail).fetch_recent("2026-07-18", 7) == []


def test_fetch_recent_retries_and_recovers_from_rate_limit():
    calls = {"n": 0}

    def fake_get(*args, **kwargs):
        calls["n"] += 1
        return _Resp([], status=429) if calls["n"] == 1 else _Resp([_doc()])

    got = ADSSource("secret", http_get=fake_get, request_delay=0).fetch("2026-07-18")
    assert [p.id for p in got] == ["ads:2026ApJ...999...1A"]
    assert calls["n"] == 2


def test_fetch_recent_skips_malformed_ads_record():
    bad = {"bibcode": "", "title": [], "entdate": "not-a-date"}
    src = ADSSource("secret", http_get=lambda *a, **k: _Resp([bad]), request_delay=0)
    assert src.fetch("2026-07-18") == []
