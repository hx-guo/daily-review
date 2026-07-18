import re
from gdr.models import Paper


def _norm_title(title: str) -> str:
    return re.sub(r"\s+", " ", title).strip().lower()


def _key(p: Paper) -> str:
    if p.doi:
        return f"doi:{p.doi.strip().lower()}"
    if p.id:
        return f"id:{p.id}"
    return f"title:{_norm_title(p.title)}"


def dedupe(papers: list[Paper]) -> list[Paper]:
    seen: set[str] = set()
    title_seen: set[str] = set()
    out: list[Paper] = []
    for p in papers:
        k = _key(p)
        t = _norm_title(p.title)
        if k in seen or t in title_seen:
            continue
        seen.add(k)
        title_seen.add(t)
        out.append(p)
    return out
