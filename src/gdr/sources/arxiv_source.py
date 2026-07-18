import datetime as dt
import feedparser
import requests
from gdr import config
from gdr.models import Paper
from gdr.sources.base import Source

ARXIV_API = "http://export.arxiv.org/api/query"


def _arxiv_id(entry_id: str) -> str:
    # "http://arxiv.org/abs/2607.00001v1" -> "arxiv:2607.00001"
    tail = entry_id.rsplit("/abs/", 1)[-1]
    if "v" in tail:
        tail = tail.split("v")[0]
    return f"arxiv:{tail}"


def _entry_to_paper(e) -> Paper:
    pdf_url = None
    for link in e.get("links", []):
        if link.get("title") == "pdf" or link.get("type") == "application/pdf":
            pdf_url = link.get("href")
    categories = [t.get("term") for t in e.get("tags", []) if t.get("term")]
    return Paper(
        id=_arxiv_id(e.id),
        source="arxiv",
        title=e.title.strip().replace("\n", " "),
        authors=[a.name for a in e.get("authors", [])],
        abstract=e.get("summary", "").strip().replace("\n", " "),
        categories=categories,
        published=e.get("published", "")[:10],
        url=e.get("link", ""),
        pdf_url=pdf_url,
        doi=e.get("arxiv_doi"),
    )


def parse_atom_all(xml: str) -> list[Paper]:
    feed = feedparser.parse(xml)
    return [_entry_to_paper(e) for e in feed.entries]


def parse_atom(xml: str, date: str) -> list[Paper]:
    return [p for p in parse_atom_all(xml) if p.published == date]


class ArxivSource(Source):
    def __init__(self, categories: list[str], http_get=requests.get, max_results: int = 300, page_size=None):
        self.categories = categories
        self._http_get = http_get
        self.max_results = max_results
        self.page_size = page_size or config.ARXIV_PAGE_SIZE

    def fetch(self, date: str) -> list[Paper]:
        query = " OR ".join(f"cat:{c}" for c in self.categories)
        params = {
            "search_query": query,
            "start": 0,
            "max_results": self.max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        resp = self._http_get(ARXIV_API, params=params, timeout=60)
        resp.raise_for_status()
        return parse_atom(resp.text, date)

    def fetch_recent(self, end_date: str, days: int) -> list[Paper]:
        start_date = (dt.date.fromisoformat(end_date) - dt.timedelta(days=days - 1)).isoformat()
        query = " OR ".join(f"cat:{c}" for c in self.categories)
        collected: list[Paper] = []
        offset = 0
        while True:
            params = {"search_query": query, "start": offset, "max_results": self.page_size,
                      "sortBy": "submittedDate", "sortOrder": "descending"}
            resp = self._http_get(ARXIV_API, params=params, timeout=60)
            resp.raise_for_status()
            batch = parse_atom_all(resp.text)
            if not batch:
                break
            reached_older = False
            for p in batch:
                if p.published > end_date:
                    continue
                if p.published < start_date:
                    reached_older = True
                    continue
                collected.append(p)
            if reached_older or len(batch) < self.page_size:
                break
            offset += self.page_size
        return collected
