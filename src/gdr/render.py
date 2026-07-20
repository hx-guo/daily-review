import html
import re
import shutil
from datetime import date as _date
from pathlib import Path
from urllib.parse import quote

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

from gdr.store import Store
from gdr.models import DayData

_LAYER_ORDER = {"core": 0, "related": 1, "edge": 2}
_WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
_ROMAN = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
          "XI", "XII", "XIII", "XIV", "XV"]


def _ordered_items(day: DayData) -> list[dict]:
    return sorted(day.items, key=lambda it: (_LAYER_ORDER.get(it["score"].layer, 9),
                                             -it["score"].score))


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


_CITE_RE = re.compile(r"\[\[(.+?)\]\]")


def _cite_href(label: str, cmap: dict) -> str:
    """Resolve a citation label to a link. Prefer an arXiv id / DOI *only* when the
    model grounded one from the paper text; otherwise fall back to an ADS search of
    the label so a chip never points at a wrongly-guessed specific paper."""
    c = cmap.get(label)
    if c:
        aid = (c.get("arxiv") or "").replace("arXiv:", "").replace("arxiv:", "").strip()
        if aid:
            return f"https://arxiv.org/abs/{aid}"
        doi = (c.get("doi") or "").strip()
        if doi:
            return "https://doi.org/" + doi
    return "https://ui.adsabs.harvard.edu/search/q=" + quote(label)


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


def render_site(store: Store, out_dir: Path, templates_dir: Path, static_dir: Path) -> None:
    out_dir = Path(out_dir)
    (out_dir / "day").mkdir(parents=True, exist_ok=True)
    env = Environment(loader=FileSystemLoader(str(templates_dir)),
                      autoescape=select_autoescape(["html"]))
    env.globals["render_authors"] = render_authors
    env.globals["render_outlook"] = render_outlook
    env.globals["arxiv_id"] = arxiv_id
    env.globals["ROMAN"] = _ROMAN
    days = store.list_days()
    loaded = [(d, store.load_day(d)) for d in days]
    # Home page + as-of date use the newest day that actually HAS papers. The sync model never
    # saves an empty day, but a stale/empty file must not wedge the home page onto an empty date.
    home_date = next((d for d, day in loaded if day.items), days[0] if days else None)
    latest_date = home_date

    day_tmpl = env.get_template("day.html")
    index_tmpl = env.get_template("index.html")
    archive_tmpl = env.get_template("archive.html")

    for date, day in loaded:
        items = _ordered_items(day)
        main_items = [it for it in items if it["score"].layer != "edge"]
        edge_items = [it for it in items if it["score"].layer == "edge"]
        core_items = [it for it in items if it["score"].layer == "core"]
        related_items = [it for it in items if it["score"].layer == "related"]
        meta = _masthead(date, len(core_items), len(related_items), len(edge_items))
        ctx = dict(day=day, items=items, main_items=main_items, edge_items=edge_items,
                   core_items=core_items, related_items=related_items, meta=meta,
                   latest_date=latest_date)
        (out_dir / "day" / f"{date}.html").write_text(
            day_tmpl.render(static_prefix="../", **ctx), encoding="utf-8")
        if date == home_date:
            (out_dir / "index.html").write_text(
                index_tmpl.render(static_prefix="", **ctx), encoding="utf-8")

    (out_dir / "archive.html").write_text(
        archive_tmpl.render(days=days, static_prefix="", latest_date=latest_date), encoding="utf-8")

    dst_static = out_dir / "static"
    if dst_static.exists():
        shutil.rmtree(dst_static)
    shutil.copytree(static_dir, dst_static)
