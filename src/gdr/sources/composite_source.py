from __future__ import annotations

import sys

from gdr.dedup import dedupe
from gdr.models import Paper
from gdr.sources.base import Source


class CompositeSource(Source):
    """Combine independent sources while keeping one source failure isolated."""

    def __init__(self, sources: list[Source]):
        self.sources = list(sources)

    def _collect(self, method: str, *args) -> list[Paper]:
        papers: list[Paper] = []
        for source in self.sources:
            try:
                papers.extend(getattr(source, method)(*args))
            except Exception as exc:
                name = type(source).__name__
                print(f"[gdr] source {name} failed: {exc}", file=sys.stderr)
        return dedupe(papers)

    def fetch(self, date: str) -> list[Paper]:
        return self._collect("fetch", date)

    def fetch_recent(self, end_date: str, days: int) -> list[Paper]:
        return self._collect("fetch_recent", end_date, days)
