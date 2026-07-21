"""Resolve the citation records the write model extracts from a paper's reference
list into concrete, verified links.

Primary resolver is ADS (astro-specialised — returns a bibcode always, plus arXiv id
/ DOI when known); Crossref is the token-free fallback. Every candidate is verified by
first-author surname + year before it is accepted, so a wrong search hit is dropped
rather than mis-linked. Unresolved citations keep `url=""`; the renderer then falls
back to an ADS search of the reference string.
"""
from __future__ import annotations

import re

import requests

from gdr import config

_YEAR_RE = re.compile(r"(?:19|20)\d{2}")


def _year(v) -> int | None:
    if v is None:
        return None
    m = _YEAR_RE.search(str(v))
    return int(m.group(0)) if m else None


def _surname(s: str) -> str:
    """Reduce an author string to a bare lowercase surname for matching.
    Handles 'Illarionov, A. F.' (family-first), 'Shakura & Sunyaev', 'Gnarini'."""
    s = (s or "").strip()
    if "," in s:                                   # ADS style: 'Family, Given'
        s = s.split(",")[0]
    else:                                          # drop coauthors + trailing year
        s = re.split(r"\s*&\s*|\s+and\s+", s)[0]
        s = _YEAR_RE.sub("", s)
        toks = s.split()
        s = toks[-1] if toks else ""               # 'A. B. Surname' -> Surname
    return re.sub(r"[^a-z]", "", s.lower())


def _verify(want_sur: str, want_year: int | None, cand_sur: str, cand_year: int | None) -> bool:
    if not want_sur or not cand_sur:
        return False
    if want_sur not in cand_sur and cand_sur not in want_sur:
        return False
    if want_year and cand_year and abs(want_year - cand_year) > 1:
        return False
    return True


def _build_url(arxiv: str, doi: str, bibcode: str) -> str:
    if arxiv:
        return f"https://arxiv.org/abs/{arxiv}"
    if doi:
        return "https://doi.org/" + doi
    if bibcode:
        return "https://ui.adsabs.harvard.edu/abs/" + bibcode
    return ""


def _ads_search(q, token, http_get):
    try:
        r = http_get(config.ADS_API_URL,
                     headers={"Authorization": f"Bearer {token}"},
                     params={"q": q, "fl": "bibcode,author,year,doi,identifier,property", "rows": 5},
                     timeout=30)
        if getattr(r, "status_code", None) != 200:
            return []
        return r.json().get("response", {}).get("docs", [])
    except Exception:
        return []


def _pick(docs, want_sur, want_year):
    verified = [d for d in docs
                if _verify(want_sur, want_year, _surname((d.get("author") or [""])[0]), _year(d.get("year")))]
    if not verified:
        return None
    # Prefer a refereed (journal) version over conference proceedings / abstracts.
    refereed = [d for d in verified if "REFEREED" in (d.get("property") or [])]
    d = (refereed or verified)[0]
    ids = d.get("identifier") or []
    arxiv = next((i.split(":", 1)[-1] for i in ids if i.lower().startswith("arxiv:")), "")
    doi = (d.get("doi") or [""])[0] if d.get("doi") else ""
    bibcode = d.get("bibcode", "") or ""
    return {"arxiv": arxiv, "doi": doi, "bibcode": bibcode, "source": "ads",
            "url": _build_url(arxiv, doi, bibcode)}


def _ads_resolve(want_sur, want_year, cite, token, http_get):
    base = f'author:"{want_sur}"' + (f" year:{want_year}" if want_year else "")
    title = (cite.get("title") or "").strip()
    words = re.findall(r"[A-Za-z]{4,}", title)[:8]
    # Pass 1: exact-ish title phrase (high precision — picks the canonical journal paper).
    # Pass 2: title words as free-text relevance terms (high recall — catches papers whose
    # title wording differs from the model's). Take the first verified hit from either.
    queries = []
    if title:
        queries.append(f'{base} title:"{title[:80]}"')
    if words:
        queries.append(f"{base} " + " ".join(words))
    if not queries:
        queries.append(base)
    for q in queries:
        rec = _pick(_ads_search(q, token, http_get), want_sur, want_year)
        if rec:
            return rec
    return None


def _crossref_resolve(want_sur, want_year, cite, mailto, http_get):
    query = (cite.get("ref") or cite.get("label") or "").strip()
    if not query:
        return None
    try:
        r = http_get(config.CROSSREF_API_URL,
                     params={"query.bibliographic": query, "rows": 1, "mailto": mailto},
                     timeout=30)
        if getattr(r, "status_code", None) != 200:
            return None
        items = r.json().get("message", {}).get("items", [])
    except Exception:
        return None
    if not items:
        return None
    m = items[0]
    authors = m.get("author") or []
    cand_sur = _surname(authors[0].get("family", "")) if authors else ""
    cand_year = None
    dp = (m.get("issued", {}) or {}).get("date-parts") or [[None]]
    if dp and dp[0]:
        cand_year = _year(dp[0][0])
    if not _verify(want_sur, want_year, cand_sur, cand_year):
        return None
    doi = m.get("DOI", "") or ""
    return {"arxiv": "", "doi": doi, "bibcode": "", "source": "crossref",
            "url": _build_url("", doi, "")}


def resolve_one(cite: dict, ads_token: str = "", mailto: str = "", http_get=requests.get) -> dict:
    """Return a copy of `cite` enriched with arxiv/doi/bibcode/url/source/verified."""
    out = dict(cite)
    out.setdefault("arxiv", "")
    out.setdefault("doi", "")
    out.setdefault("bibcode", "")
    out.setdefault("url", "")
    out.setdefault("source", "")
    out["verified"] = False
    want_sur = _surname(cite.get("authors") or cite.get("label") or "")
    want_year = _year(cite.get("year") or cite.get("label"))
    rec = None
    if ads_token:
        rec = _ads_resolve(want_sur, want_year, cite, ads_token, http_get)
    if rec is None:
        rec = _crossref_resolve(want_sur, want_year, cite, mailto, http_get)
    if rec:
        out.update(rec)
        out["verified"] = bool(rec.get("url"))
    return out


def resolve_citations(citations, ads_token: str = "", mailto: str = "", http_get=requests.get) -> list[dict]:
    if not citations:
        return []
    return [resolve_one(c, ads_token=ads_token, mailto=mailto, http_get=http_get) for c in citations]


def resolve_summary(summary, ads_token: str = "", mailto: str = "", http_get=requests.get):
    """Resolve a PaperSummary's citations in place (no-op if it has none). Returns it."""
    if summary is not None and getattr(summary, "citations", None):
        summary.citations = resolve_citations(summary.citations, ads_token=ads_token,
                                               mailto=mailto, http_get=http_get)
    return summary
