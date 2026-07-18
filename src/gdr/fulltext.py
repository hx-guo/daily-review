import requests
from bs4 import BeautifulSoup
from gdr import config
from gdr.models import Paper


def extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["nav", "footer", "script", "style"]):
        tag.decompose()
    body = soup.find("article") or soup.body or soup
    text = body.get_text(separator="\n")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines)


def fetch_fulltext(paper: Paper, http_get=requests.get) -> str | None:
    if paper.source != "arxiv":
        return None
    bare = paper.id.split(":", 1)[-1]
    url = f"https://arxiv.org/html/{bare}"
    try:
        resp = http_get(url, timeout=60)
    except Exception:
        return None
    if getattr(resp, "status_code", None) != 200:
        return None
    text = extract_text(resp.text)
    if not text:
        return None
    return text[: config.FULLTEXT_MAX_CHARS]
