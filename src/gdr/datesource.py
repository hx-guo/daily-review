"""Fetch the three academic dates from Crossref and arXiv.

Crossref is token-free and gives the journal dates ADS cannot: `published-online`
is usually day-precise where ADS's `pubdate` is month-only, and some publishers
deposit the acceptance date in the `assertion` array. Coverage is uneven by
publisher (AAS and Springer deposit acceptance, APS and Elsevier do not), so
every field here is best-effort: a missing or unparseable value stays empty.
"""
from __future__ import annotations

import feedparser
import requests

from gdr import config
from gdr.dates import parse_partial_date, pick_published

ARXIV_API = "http://export.arxiv.org/api/query"


def _assertion(message: dict, needle: str) -> str:
    for item in (message.get("assertion") or []):
        name = f"{item.get('name', '')} {item.get('label', '')}".lower()
        if needle in name:
            date, _ = parse_partial_date(item.get("value"))
            if date:
                return date
    return ""


def fetch_crossref_dates(doi: str, mailto: str = "",
                         http_get=requests.get) -> dict:
    """Journal dates for one DOI. Returns {} when the DOI is unknown or the
    request fails — callers treat that as "no journal dates yet"."""
    doi = (doi or "").strip()
    if not doi:
        return {}
    try:
        response = http_get(f"{config.CROSSREF_API_URL}/{doi}",
                            params={"mailto": mailto}, timeout=30)
        if getattr(response, "status_code", None) != 200:
            return {}
        message = response.json().get("message", {})
    except Exception:
        return {}
    if not isinstance(message, dict):
        return {}
    published = pick_published(
        online=(message.get("published-online") or {}).get("date-parts"),
        printed=(message.get("published-print") or {}).get("date-parts"),
        created=(message.get("created") or {}).get("date-parts"),
    )
    return {
        "accepted": _assertion(message, "accept"),
        "published": published["date"],
        "published_precision": published["precision"],
        "published_source": published["source"],
        "received": _assertion(message, "receiv"),
    }


def fetch_arxiv_v1_date(arxiv_id: str, http_get=requests.get) -> str:
    """arXiv v1 submission date (the preprint date). Empty on any failure."""
    arxiv_id = (arxiv_id or "").strip()
    if not arxiv_id:
        return ""
    try:
        response = http_get(ARXIV_API,
                            params={"id_list": arxiv_id, "max_results": 1},
                            timeout=30)
        entries = feedparser.parse(getattr(response, "text", "")).entries
    except Exception:
        return ""
    if not entries:
        return ""
    return str(entries[0].get("published", ""))[:10]
