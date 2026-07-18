from pathlib import Path
from gdr.sources.arxiv_source import parse_atom, parse_atom_all, ArxivSource

SAMPLE = (Path(__file__).parent / "fixtures" / "arxiv_sample.xml").read_text()

def _atom(entries):  # entries: list of (id, published_date)
    items = "".join(
        f'<entry><id>http://arxiv.org/abs/{i}v1</id>'
        f'<published>{pub}T00:00:00Z</published><title>t {i}</title>'
        f'<summary>s</summary><author><name>A</name></author>'
        f'<link href="http://arxiv.org/abs/{i}v1" rel="alternate" type="text/html"/>'
        f'<category term="astro-ph.HE" scheme="http://arxiv.org/schemas/atom"/></entry>'
        for i, pub in entries)
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<feed xmlns="http://www.w3.org/2005/Atom" '
            'xmlns:arxiv="http://arxiv.org/schemas/atom">' + items + '</feed>')

def test_parse_atom_filters_by_date():
    papers = parse_atom(SAMPLE, date="2026-07-18")
    assert len(papers) == 1
    p = papers[0]
    assert p.id == "arxiv:2607.00001"
    assert p.title == "A magnetar giant flare study"
    assert p.authors == ["Alice Author", "Bob Boss"]
    assert p.categories == ["astro-ph.HE"]
    assert p.pdf_url == "http://arxiv.org/pdf/2607.00001v1"
    assert p.doi == "10.0000/example"
    assert p.published == "2026-07-18"

def test_fetch_uses_injected_http_get():
    class Resp:
        text = SAMPLE
        def raise_for_status(self): pass
    captured = {}
    def fake_get(url, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        return Resp()
    src = ArxivSource(categories=["astro-ph.HE", "gr-qc"], http_get=fake_get)
    papers = src.fetch("2026-07-18")
    assert len(papers) == 1
    assert "astro-ph.HE" in captured["params"]["search_query"]
    assert "gr-qc" in captured["params"]["search_query"]

def test_parse_atom_all_returns_everything():
    xml = _atom([("2607.1", "2026-07-16"), ("2607.2", "2026-07-15")])
    assert len(parse_atom_all(xml)) == 2

def test_fetch_recent_paginates_and_windows():
    all_entries = [("2607.17", "2026-07-17"), ("2607.16", "2026-07-16"),
                   ("2607.15", "2026-07-15"), ("2607.14", "2026-07-14"),
                   ("2607.13", "2026-07-13")]  # descending by submittedDate
    def fake_get(url, params=None, timeout=None):
        start = params["start"]; n = params["max_results"]
        page = all_entries[start:start + n]
        class R:
            text = _atom(page)
            def raise_for_status(self): pass
        return R()
    src = ArxivSource(["astro-ph.HE"], http_get=fake_get, page_size=2, request_delay=0)
    got = src.fetch_recent("2026-07-16", days=3)   # window [2026-07-14, 2026-07-16]
    assert sorted(p.id for p in got) == ["arxiv:2607.14", "arxiv:2607.15", "arxiv:2607.16"]


def test_fetch_recent_terminates_on_misbehaving_pagination():
    page = [("2607.16", "2026-07-16"), ("2607.15", "2026-07-15")]
    def fake_get(url, params=None, timeout=None):   # ignores `start`, always same page
        class R:
            text = _atom(page)
            def raise_for_status(self): pass
        return R()
    src = ArxivSource(["astro-ph.HE"], http_get=fake_get, page_size=2, request_delay=0)
    got = src.fetch_recent("2026-07-16", days=3)
    assert sorted(p.id for p in got) == ["arxiv:2607.15", "arxiv:2607.16"]  # collected once, no hang


def test_fetch_recent_retries_on_429_then_succeeds():
    good = _atom([("2607.16", "2026-07-16")])
    calls = {"n": 0}
    def fake_get(url, params=None, timeout=None):
        calls["n"] += 1
        class R:
            def __init__(self, code, text):
                self.status_code = code
                self.text = text
        return R(429, "") if calls["n"] == 1 else R(200, good)
    src = ArxivSource(["astro-ph.HE"], http_get=fake_get, page_size=100, request_delay=0)
    got = src.fetch_recent("2026-07-16", days=1)
    assert [p.id for p in got] == ["arxiv:2607.16"]   # retry recovered the page
    assert calls["n"] == 2                             # one retry


def test_fetch_recent_gives_up_gracefully_on_persistent_429():
    def fake_get(url, params=None, timeout=None):
        class R:
            status_code = 429
            text = ""
        return R()
    src = ArxivSource(["astro-ph.HE"], http_get=fake_get, page_size=100,
                      request_delay=0, max_retries=2)
    got = src.fetch_recent("2026-07-16", days=1)
    assert got == []   # no papers, but NO exception raised (pipeline must not crash)
