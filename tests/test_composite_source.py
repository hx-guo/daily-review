from gdr.models import Paper
from gdr.sources.base import Source
from gdr.sources.composite_source import CompositeSource


class _Source(Source):
    def __init__(self, papers=None, error=None):
        self.papers = papers or []
        self.error = error

    def fetch(self, date):
        if self.error:
            raise self.error
        return list(self.papers)

    def fetch_recent(self, end_date, days):
        return self.fetch(end_date)


def _paper(pid, source, title, external_ids=None):
    return Paper(id=pid, source=source, title=title, authors=[], abstract="",
                 categories=[], published="2026-07-18", url="",
                 external_ids=external_ids or {})


def test_composite_keeps_first_source_and_merges_cross_source_ids():
    arxiv = _paper("arxiv:2607.1", "arxiv", "Same Paper", {"arxiv": "2607.1"})
    ads = _paper("ads:2026ApJ...1A", "ads", "Same Paper", {"ads": "2026ApJ...1A"})
    got = CompositeSource([_Source([arxiv]), _Source([ads])]).fetch_recent("2026-07-18", 7)
    assert got == [arxiv]
    assert got[0].external_ids == {"arxiv": "2607.1", "ads": "2026ApJ...1A"}


def test_composite_source_failure_does_not_hide_other_source(capsys):
    paper = _paper("arxiv:1", "arxiv", "Available")
    got = CompositeSource([_Source(error=RuntimeError("ADS down")), _Source([paper])]).fetch("2026-07-18")
    assert got == [paper]
    assert "ADS down" in capsys.readouterr().err
