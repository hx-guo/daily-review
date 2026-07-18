from pathlib import Path
from gdr.models import Paper
from gdr.fulltext import extract_text, fetch_fulltext

HTML = (Path(__file__).parent / "fixtures" / "arxiv_html_sample.html").read_text()

def _paper():
    return Paper(id="arxiv:2607.00001", source="arxiv", title="t", authors=[],
                 abstract="a", categories=[], published="2026-07-18", url="")

def test_extract_text_gets_body_content():
    text = extract_text(HTML)
    assert "magnetar giant flare" in text.lower()
    assert "detected by GECAM" in text

def test_fetch_fulltext_success():
    class Resp:
        status_code = 200
        text = HTML
    def fake_get(url, timeout=None):
        assert "2607.00001" in url
        return Resp()
    out = fetch_fulltext(_paper(), http_get=fake_get)
    assert out is not None and "GECAM" in out

def test_fetch_fulltext_404_returns_none():
    class Resp:
        status_code = 404
        text = ""
    out = fetch_fulltext(_paper(), http_get=lambda url, timeout=None: Resp())
    assert out is None

def test_fetch_fulltext_non_arxiv_returns_none():
    p = _paper()
    p.source = "journal"
    assert fetch_fulltext(p, http_get=lambda url, timeout=None: None) is None
