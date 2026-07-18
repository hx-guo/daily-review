from pathlib import Path
from gdr.sources.arxiv_source import parse_atom, ArxivSource

SAMPLE = (Path(__file__).parent / "fixtures" / "arxiv_sample.xml").read_text()

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
