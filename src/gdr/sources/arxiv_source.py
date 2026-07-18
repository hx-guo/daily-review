import feedparser
import requests
from gdr.models import Paper
from gdr.sources.base import Source

ARXIV_API = "http://export.arxiv.org/api/query"


def _arxiv_id(entry_id: str) -> str:
    # "http://arxiv.org/abs/2607.00001v1" -> "arxiv:2607.00001"
    tail = entry_id.rsplit("/abs/", 1)[-1]
    if "v" in tail:
        tail = tail.split("v")[0]
    return f"arxiv:{tail}"


def parse_atom(xml: str, date: str) -> list[Paper]:
    feed = feedparser.parse(xml)
    papers: list[Paper] = []
    for e in feed.entries:
        published = e.get("published", "")[:10]
        if published != date:
            continue
        pdf_url = None
        for link in e.get("links", []):
            if link.get("title") == "pdf" or link.get("type") == "application/pdf":
                pdf_url = link.get("href")
        categories = [t.get("term") for t in e.get("tags", []) if t.get("term")]
        papers.append(
            Paper(
                id=_arxiv_id(e.id),
                source="arxiv",
                title=e.title.strip().replace("\n", " "),
                authors=[a.name for a in e.get("authors", [])],
                abstract=e.get("summary", "").strip().replace("\n", " "),
                categories=categories,
                published=published,
                url=e.get("link", ""),
                pdf_url=pdf_url,
                doi=e.get("arxiv_doi"),
            )
        )
    return papers


class ArxivSource(Source):
    def __init__(self, categories: list[str], http_get=requests.get, max_results: int = 300):
        self.categories = categories
        self._http_get = http_get
        self.max_results = max_results

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
