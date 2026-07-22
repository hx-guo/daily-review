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


def test_fetch_fulltext_ads_record_uses_linked_arxiv_id():
    p = _paper()
    p.id = "ads:2026ApJ...1A"
    p.source = "ads"
    p.external_ids = {"ads": "2026ApJ...1A", "arxiv": "2607.00001"}

    class Resp:
        status_code = 200
        text = HTML

    def fake_get(url, timeout=None):
        assert url == "https://arxiv.org/html/2607.00001"
        return Resp()

    assert "GECAM" in fetch_fulltext(p, http_get=fake_get)

def test_fetch_fulltext_text_access_raises_returns_none():
    class Resp:
        status_code = 200
        @property
        def text(self):
            raise ValueError("decode boom")
    assert fetch_fulltext(_paper(), http_get=lambda url, timeout=None: Resp()) is None

def test_fetch_fulltext_empty_html_returns_none():
    class Resp:
        status_code = 200
        text = "<html><body></body></html>"
    assert fetch_fulltext(_paper(), http_get=lambda url, timeout=None: Resp()) is None
