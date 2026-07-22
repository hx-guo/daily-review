import re
from gdr.models import Paper


def _norm_title(title: str) -> str:
    return re.sub(r"\s+", " ", title).strip().lower()


def paper_keys(p: Paper) -> set[str]:
    """Stable identities suitable for both cross-source dedupe and seen-indexes."""
    keys = set()
    if p.id:
        keys.add(p.id.strip().lower())
    if p.doi:
        keys.add(f"doi:{p.doi.strip().lower()}")
    title = _norm_title(p.title)
    if title:
        keys.add(f"title:{title}")
    for kind, value in (getattr(p, "external_ids", None) or {}).items():
        kind = str(kind).strip().lower()
        value = str(value).strip()
        if not kind or not value:
            continue
        # Values may already carry their prefix (especially imported legacy data).
        prefix = f"{kind}:"
        keys.add(value.lower() if value.lower().startswith(prefix)
                 else f"{prefix}{value.lower()}")
    return keys


def _merge(primary: Paper, duplicate: Paper) -> None:
    """Enrich the first-source record without changing its canonical identity."""
    primary.external_ids = {
        **(getattr(duplicate, "external_ids", None) or {}),
        **(getattr(primary, "external_ids", None) or {}),
    }
    if not primary.doi and duplicate.doi:
        primary.doi = duplicate.doi
    if not primary.pdf_url and duplicate.pdf_url:
        primary.pdf_url = duplicate.pdf_url
    if not primary.abstract and duplicate.abstract:
        primary.abstract = duplicate.abstract
    for category in duplicate.categories:
        if category not in primary.categories:
            primary.categories.append(category)


def dedupe(papers: list[Paper]) -> list[Paper]:
    identity_map: dict[str, Paper] = {}
    title_map: dict[str, Paper] = {}
    out: list[Paper] = []
    for p in papers:
        keys = paper_keys(p)
        existing = next((identity_map[k] for k in keys if k in identity_map), None)
        t = _norm_title(p.title)
        if existing is None and t:
            existing = title_map.get(t)
        if existing is not None:
            _merge(existing, p)
            for k in paper_keys(existing) | keys:
                identity_map[k] = existing
            continue
        out.append(p)
        for k in keys:
            identity_map[k] = p
        if t:
            title_map[t] = p
    return out
