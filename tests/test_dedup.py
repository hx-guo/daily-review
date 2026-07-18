from gdr.models import Paper
from gdr.dedup import dedupe

def _p(id, doi=None, title="T"):
    return Paper(id=id, source="arxiv", title=title, authors=[], abstract="",
                 categories=[], published="2026-07-18", url="", pdf_url=None, doi=doi)

def test_dedupe_by_id():
    out = dedupe([_p("arxiv:1", title="T1"), _p("arxiv:1", title="T1"), _p("arxiv:2", title="T2")])
    assert [p.id for p in out] == ["arxiv:1", "arxiv:2"]

def test_dedupe_by_doi_across_ids():
    out = dedupe([_p("arxiv:1", doi="10.1/x"), _p("arxiv:2", doi="10.1/x")])
    assert [p.id for p in out] == ["arxiv:1"]

def test_dedupe_by_title_when_no_doi():
    out = dedupe([_p("arxiv:1", title="A  GRB Study"), _p("arxiv:2", title="a grb study")])
    assert [p.id for p in out] == ["arxiv:1"]
