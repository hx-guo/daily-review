import shutil
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from gdr.store import Store
from gdr.models import DayData

_LAYER_ORDER = {"core": 0, "related": 1, "edge": 2}


def _ordered_items(day: DayData) -> list[dict]:
    return sorted(day.items, key=lambda it: (_LAYER_ORDER.get(it["score"].layer, 9),
                                             -it["score"].score))


def render_site(store: Store, out_dir: Path, templates_dir: Path, static_dir: Path) -> None:
    out_dir = Path(out_dir)
    (out_dir / "day").mkdir(parents=True, exist_ok=True)
    env = Environment(loader=FileSystemLoader(str(templates_dir)),
                      autoescape=select_autoescape(["html"]))
    days = store.list_days()
    latest_date = days[0] if days else None

    day_tmpl = env.get_template("day.html")
    index_tmpl = env.get_template("index.html")
    archive_tmpl = env.get_template("archive.html")

    for i, date in enumerate(days):
        day = store.load_day(date)
        items = _ordered_items(day)
        html = day_tmpl.render(day=day, items=items, static_prefix="../", latest_date=latest_date)
        (out_dir / "day" / f"{date}.html").write_text(html, encoding="utf-8")
        if i == 0:
            idx = index_tmpl.render(day=day, items=items, static_prefix="", latest_date=latest_date)
            (out_dir / "index.html").write_text(idx, encoding="utf-8")

    (out_dir / "archive.html").write_text(
        archive_tmpl.render(days=days, static_prefix="", latest_date=latest_date), encoding="utf-8")

    dst_static = out_dir / "static"
    if dst_static.exists():
        shutil.rmtree(dst_static)
    shutil.copytree(static_dir, dst_static)
