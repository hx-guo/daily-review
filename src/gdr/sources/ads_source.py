from __future__ import annotations

import datetime as dt
import re
import time

import requests

from gdr import config
from gdr.models import Paper
from gdr.sources.base import Source


_ARXIV_ID_RE = re.compile(r"(?:arxiv:)?(\d{4}\.\d{4,5}(?:v\d+)?|[a-z.-]+/\d{7}(?:v\d+)?)$", re.I)


def _first(value) -> str:
    if isinstance(value, list):
        value = value[0] if value else ""
    return str(value or "").strip()


def _list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _doi(doc: dict) -> str | None:
    values = _list(doc.get("doi"))
    clean = [str(v).strip() for v in values if str(v).strip()]
    # ADS sometimes includes the arXiv DOI as well as the journal DOI. For a
    # published record, the journal DOI is the useful canonical identifier.
    return next((v for v in clean if not v.lower().startswith("10.48550/arxiv.")),
                clean[0] if clean else None)


def _arxiv_id(doc: dict) -> str:
    for raw in _list(doc.get("identifier")):
        value = str(raw).strip()
        match = _ARXIV_ID_RE.search(value)
        if match:
            return re.sub(r"v\d+$", "", match.group(1), flags=re.I)
    return ""


def _date(doc: dict) -> str:
    """Use ADS entry date as the daily-review announcement date.

    Journal publication dates in ADS are often month-only. `entdate` is a true
    calendar day and is the closest analogue to arXiv's daily announcement date.
    """
    for field in ("entdate", "entry_date", "date"):
        candidate = _first(doc.get(field))[:10]
        try:
            dt.date.fromisoformat(candidate)
            return candidate
        except (TypeError, ValueError):
            continue
    return ""


def doc_to_paper(doc: dict) -> Paper:
    bibcode = _first(doc.get("bibcode"))
    aid = _arxiv_id(doc)
    doi = _doi(doc)
    title = _first(doc.get("title")).replace("\n", " ")
    authors = _list(doc.get("author"))
    categories = []
    for value in _list(doc.get("arxiv_class")) + _list(doc.get("keyword")):
        value = str(value).strip()
        if value and value not in categories:
            categories.append(value)

    external_ids = {"ads": bibcode}
    if aid:
        external_ids["arxiv"] = aid
    if doi:
        external_ids["doi"] = doi

    return Paper(
        id=f"ads:{bibcode}",
        source="ads",
        title=title,
        authors=[str(a).strip() for a in authors if str(a).strip()],
        abstract=_first(doc.get("abstract")).replace("\n", " "),
        categories=categories,
        published=_date(doc),
        url=f"https://ui.adsabs.harvard.edu/abs/{bibcode}/abstract",
        pdf_url=f"https://arxiv.org/pdf/{aid}" if aid else None,
        doi=doi,
        external_ids=external_ids,
    )


class ADSSource(Source):
    """Published astronomy papers newly indexed by NASA ADS."""

    def __init__(self, token: str, query: str | None = None, http_get=requests.get,
                 page_size: int | None = None, request_delay: float | None = None,
                 max_retries: int = 3):
        self.token = token.strip()
        self.query = (query or config.ADS_INGEST_QUERY).strip()
        self._http_get = http_get
        self.page_size = page_size or config.ADS_PAGE_SIZE
        self.request_delay = (config.ADS_REQUEST_DELAY
                              if request_delay is None else request_delay)
        self.max_retries = max_retries

    def _get_page(self, query: str, offset: int):
        params = {
            "q": query,
            "fl": ("bibcode,title,author,abstract,keyword,arxiv_class,entdate,"
                   "entry_date,date,pubdate,doi,identifier,property,pub,doctype,esources"),
            "start": offset,
            "rows": self.page_size,
            "sort": "entry_date desc",
        }
        for attempt in range(self.max_retries):
            try:
                response = self._http_get(
                    config.ADS_API_URL,
                    headers={"Authorization": f"Bearer {self.token}"},
                    params=params,
                    timeout=60,
                )
            except Exception:
                response = None
            if response is not None and getattr(response, "status_code", None) == 200:
                return response
            if self.request_delay:
                time.sleep(self.request_delay * (attempt + 1))
        return None

    def fetch(self, date: str) -> list[Paper]:
        return self.fetch_recent(date, 1)

    def fetch_recent(self, end_date: str, days: int) -> list[Paper]:
        if not self.token:
            return []
        start_date = (dt.date.fromisoformat(end_date) - dt.timedelta(days=days - 1)).isoformat()
        dated_query = f"({self.query}) entdate:[{start_date} TO {end_date}]"
        papers: list[Paper] = []
        offset = 0
        while True:
            response = self._get_page(dated_query, offset)
            if response is None:
                break
            try:
                payload = response.json().get("response", {})
                docs = payload.get("docs") or []
                total = int(payload.get("numFound", len(docs)))
            except (AttributeError, TypeError, ValueError):
                break
            if not docs:
                break
            for doc in docs:
                paper = doc_to_paper(doc)
                # Malformed ADS records should not poison the downstream store.
                if paper.id != "ads:" and paper.title and paper.published:
                    papers.append(paper)
            offset += len(docs)
            if offset >= total or len(docs) < self.page_size:
                break
            if self.request_delay:
                time.sleep(self.request_delay)
        return papers
