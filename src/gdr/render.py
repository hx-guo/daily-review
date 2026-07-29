import html
import re
import shutil
from datetime import date as _date
from pathlib import Path
from urllib.parse import quote

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

from gdr.store import Store

_LAYER_ORDER = {"core": 0, "related": 1, "edge": 2}
_WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
_ROMAN = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
          "XI", "XII", "XIII", "XIV", "XV"]


def group_by(items: list[dict], key: str) -> dict[str, list[dict]]:
    """Group stored items onto one of the two axes. `key` is "archive" (the
    paper's own earliest academic date) or "ingest" (the day this site saw it)."""
    field = (lambda it: it["archive_date"]) if key == "archive" else \
            (lambda it: it["dates"]["ingested"])
    groups: dict[str, list[dict]] = {}
    for item in items:
        value = field(item)
        if value:
            groups.setdefault(value, []).append(item)
    return groups


def _sorted_items(items: list[dict]) -> list[dict]:
    return sorted(items, key=lambda it: (_LAYER_ORDER.get(it["score"].layer, 9),
                                         -it["score"].score))


def versions_for(items: list[dict]) -> list[str]:
    """Ingest days that contributed to one archive day. A day that arrived in one
    piece has no versions — there is nothing to switch between."""
    dates = sorted({it["dates"]["ingested"] for it in items
                    if it["dates"].get("ingested")})
    return dates if len(dates) > 1 else []


def _version_href(date: str, version: str, latest: str) -> str:
    return f"{date}.html" if version == latest else f"{date}.as-of-{version}.html"


def page_context(axis: str, date: str, items: list[dict], *, latest_date: str,
                 prev_date: str = "", next_date: str = "",
                 versions=(), current_version: str = "") -> dict:
    from gdr.daily_review import compose_review

    ordered = _sorted_items(items)
    core = [it for it in ordered if it["score"].layer == "core"]
    related = [it for it in ordered if it["score"].layer == "related"]
    edge = [it for it in ordered if it["score"].layer == "edge"]
    return dict(axis=axis, date=date, review=compose_review(date, ordered),
                items=ordered, main_items=core + related, core_items=core,
                related_items=related, edge_items=edge,
                meta=_masthead(date, len(core), len(related), len(edge)),
                latest_date=latest_date, prev_date=prev_date, next_date=next_date,
                versions=list(versions), current_version=current_version)


def _masthead(date_str: str, n_core: int, n_related: int, n_edge: int) -> dict:
    """Journal-style masthead metadata: volume (year), issue no. (day-of-year),
    Chinese date, weekday, and per-layer counts."""
    y, m, d = (int(x) for x in date_str.split("-"))
    dt = _date(y, m, d)
    return {
        "vol": y,
        "no": dt.timetuple().tm_yday,
        "cn_date": f"{y} 年 {m} 月 {d} 日",
        "weekday": _WEEKDAYS[dt.weekday()],
        "n_core": n_core,
        "n_related": n_related,
        "n_edge": n_edge,
    }


_AFFIL_RE = re.compile(r"\(([^()]*)\)")
_ETAL_RE = re.compile(r"(,?\s*)et\s+al\.?", re.IGNORECASE)


def render_authors(paper, summary) -> Markup:
    """Render the author line per the design's Author Display Rule: affiliations in
    a lighter parenthetical span, a trailing `et al.` in italic, and a ✉ envelope
    marking the corresponding author. Works off the pre-formatted `authors_en`
    string (which already carries affiliations) and falls back to the first three
    raw author names when no English author line is available."""
    corr = ((summary.corresponding_en if summary else "") or "").strip()
    src = ((summary.authors_en if summary else "") or "").strip()
    if src:
        text = src
    else:
        names = paper.authors[:3]
        text = ", ".join(names)
        if len(paper.authors) > 3:
            text += ", et al."
    html = str(escape(text))
    html = _ETAL_RE.sub(r'\1<span class="etal">et al.</span>', html)
    html = _AFFIL_RE.sub(r'<span class="affil">(\1)</span>', html)
    if corr:
        corr_esc = str(escape(corr))
        env = '<span class="corr-mark" title="通讯作者">✉</span> '
        if corr_esc and corr_esc in html:
            html = html.replace(corr_esc, env + corr_esc, 1)
        else:
            html = env + html
    return Markup(html)


def arxiv_id(paper) -> str:
    """Bare arXiv identifier for display, e.g. `2607.15130`."""
    pid = (paper.id or "").split(":", 1)[-1]
    if pid:
        return pid
    return (paper.url or "").rstrip("/").rsplit("/", 1)[-1]


def paper_links(paper) -> list[dict[str, str]]:
    """Return stable source links for either arXiv- or ADS-origin papers."""
    external_ids = getattr(paper, "external_ids", None) or {}
    aid = str(external_ids.get("arxiv") or "").strip()
    bibcode = str(external_ids.get("ads") or "").strip()
    doi = str(getattr(paper, "doi", None) or external_ids.get("doi") or "").strip()
    if paper.source == "arxiv" and not aid:
        aid = (paper.id or "").split(":", 1)[-1]
    if paper.source == "ads" and not bibcode:
        bibcode = (paper.id or "").split(":", 1)[-1]

    known = {
        "arxiv": {"label": f"arXiv:{aid}", "url": f"https://arxiv.org/abs/{aid}"} if aid else None,
        "doi": {"label": "DOI", "url": f"https://doi.org/{doi}"} if doi else None,
        "ads": {"label": f"ADS:{bibcode}",
                "url": f"https://ui.adsabs.harvard.edu/abs/{bibcode}/abstract"} if bibcode else None,
    }
    order = [paper.source, "arxiv", "doi", "ads"]
    links = []
    seen_urls = set()
    for kind in order:
        link = known.get(kind)
        if link and link["url"] not in seen_urls:
            links.append(link)
            seen_urls.add(link["url"])
    if not links and paper.url:
        links.append({"label": (paper.source or "原文").upper(), "url": paper.url})
    return links


_CITE_RE = re.compile(r"\[\[(.+?)\]\]")


def _cite_href(label: str, cmap: dict) -> str:
    """Resolve a citation label to a link. Prefer the verified `url` the resolver
    attached (ADS bibcode / arXiv / DOI); otherwise fall back to an ADS search of the
    reference string (or label) so a chip lands on the right paper rather than a
    wrongly-guessed specific one."""
    c = cmap.get(label)
    if c:
        url = (c.get("url") or "").strip()
        if url:
            return url
        aid = (c.get("arxiv") or "").replace("arXiv:", "").replace("arxiv:", "").strip()
        if aid:
            return f"https://arxiv.org/abs/{aid}"
        doi = (c.get("doi") or "").strip()
        if doi:
            return "https://doi.org/" + doi
        query = (c.get("ref") or "").strip() or label
    else:
        query = label
    return "https://ui.adsabs.harvard.edu/search/q=" + quote(query)


def render_outlook(summary) -> Markup:
    """脉络与展望 body: escape the text, then turn inline `[[作者+年份]]` markers into
    linked citation chips. Falls back to the legacy review/relation text (no chips)
    for summaries generated before context_outlook existed."""
    text = (getattr(summary, "context_outlook", "") if summary else "") or ""
    if not text:
        legacy = ((getattr(summary, "review", "") if summary else "")
                  or (getattr(summary, "relation", "") if summary else "")) or ""
        return Markup(str(escape(legacy)))
    cmap = {}
    for c in (getattr(summary, "citations", None) or []):
        lbl = (c.get("label") or "").strip()
        if lbl:
            cmap[lbl] = c
    esc = str(escape(text))

    def _repl(m):
        raw = html.unescape(m.group(1)).strip()
        href = _cite_href(raw, cmap)
        return (f'<a class="cite" href="{escape(href)}" target="_blank" '
                f'rel="noopener">{escape(raw)}</a>')

    return Markup(_CITE_RE.sub(_repl, esc))


_WATCH_ID_RE = re.compile(
    r"[（(\[]?\s*(?:arxiv:\s*(?P<arx>\d{4}\.\d{4,5})(?:v\d+)?"
    r"|ads:\s*(?P<ads>[^）)\]\s，,]+))\s*[）)\]]?",
    re.IGNORECASE,
)


def split_watch(signal: str) -> dict:
    """继续观察 item -> {label, url, text}. The synth writes the source id either
    leading ("arxiv:2607.19298 预言的…") or trailing in full-width parens
    ("… 尚需独立后随观测确认（ads:2026ApJ..1006...56A）"); the design renders it as a
    leading dotted cite link, so pull it out here. label/url are empty when the
    signal carries no id."""
    s = (signal or "").strip()
    m = _WATCH_ID_RE.search(s)
    if not m:
        return {"label": "", "url": "", "text": s}
    arx, ads = m.group("arx"), m.group("ads")
    if arx:
        label, url = f"arXiv:{arx}", f"https://arxiv.org/abs/{arx}"
    else:
        bib = ads.strip()
        label = "ADS " + bib
        url = "https://ui.adsabs.harvard.edu/abs/" + quote(bib)
    text = (s[: m.start()] + s[m.end():]).strip(" 　·:：、，,；;")
    return {"label": label, "url": url, "text": text}


def render_site(store: Store, out_dir: Path, templates_dir: Path, static_dir: Path) -> None:
    """Render the two time axes from the stored items' cached decisions.

    `news/<ingest date>.html` groups papers by the day this site saw them;
    `day/<archive date>.html` groups the same papers by their own earliest
    academic date, however many ingest runs contributed to that day. The home
    page is always the newest news page.
    """
    out_dir = Path(out_dir)
    env = Environment(loader=FileSystemLoader(str(templates_dir)),
                      autoescape=select_autoescape(["html"]))
    env.globals["render_authors"] = render_authors
    env.globals["render_outlook"] = render_outlook
    env.globals["split_watch"] = split_watch
    env.globals["arxiv_id"] = arxiv_id
    env.globals["paper_links"] = paper_links
    env.globals["ROMAN"] = _ROMAN

    items = store.all_items()
    by_ingest = group_by(items, "ingest")
    by_archive = group_by(items, "archive")
    ingest_dates = sorted(by_ingest)
    archive_dates = sorted(by_archive)
    latest_date = ingest_dates[-1] if ingest_dates else ""

    (out_dir / "news").mkdir(parents=True, exist_ok=True)
    (out_dir / "day").mkdir(parents=True, exist_ok=True)
    day_tmpl = env.get_template("day.html")
    index_tmpl = env.get_template("index.html")
    archive_tmpl = env.get_template("archive.html")

    for i, date in enumerate(ingest_dates):
        ctx = page_context("news", date, by_ingest[date], latest_date=latest_date,
                           prev_date=ingest_dates[i - 1] if i else "",
                           next_date=ingest_dates[i + 1]
                           if i + 1 < len(ingest_dates) else "")
        (out_dir / "news" / f"{date}.html").write_text(
            day_tmpl.render(static_prefix="../", **ctx), encoding="utf-8")
        if date == latest_date:
            (out_dir / "index.html").write_text(
                index_tmpl.render(static_prefix="", **ctx), encoding="utf-8")

    for date in archive_dates:
        all_day_items = by_archive[date]
        versions = versions_for(all_day_items)
        latest_version = versions[-1] if versions else ""
        bar = [{"date": v, "href": _version_href(date, v, latest_version),
                "n": sum(1 for it in all_day_items
                         if it["dates"]["ingested"] <= v),
                "current": False} for v in versions]
        for version in [""] + versions:
            shown = (all_day_items if not version else
                     [it for it in all_day_items
                      if it["dates"]["ingested"] <= version])
            if version and version == latest_version:
                continue                       # the latest version IS the bare URL
            marked = [{**b, "current": b["date"] == version} for b in bar]
            ctx = page_context("archive", date, shown, latest_date=latest_date,
                               versions=marked, current_version=version)
            name = f"{date}.html" if not version else f"{date}.as-of-{version}.html"
            (out_dir / "day" / name).write_text(
                day_tmpl.render(static_prefix="../", **ctx), encoding="utf-8")

    (out_dir / "archive.html").write_text(
        archive_tmpl.render(days=sorted(archive_dates, reverse=True),
                            static_prefix="", latest_date=latest_date),
        encoding="utf-8")

    dst_static = out_dir / "static"
    if dst_static.exists():
        shutil.rmtree(dst_static)
    shutil.copytree(static_dir, dst_static)
