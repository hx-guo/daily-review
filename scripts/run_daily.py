import argparse
import datetime as dt
from pathlib import Path
from gdr import config
from gdr.llm import OpenCodeLLM
from gdr.sources.arxiv_source import ArxivSource
from gdr.store import Store
from gdr.pipeline import run
from gdr.render import render_site

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (default: yesterday UTC)")
    args = ap.parse_args()
    date = args.date or (dt.datetime.utcnow().date() - dt.timedelta(days=1)).isoformat()

    llm = OpenCodeLLM(api_key=config.get_api_key())
    source = ArxivSource(categories=config.ARXIV_CATEGORIES)
    store = Store(ROOT / "data")

    day = run(date, source, llm, store)
    print(f"{date}: {len(day.items)} papers")
    render_site(store, ROOT / "site", ROOT / "templates", ROOT / "static")


if __name__ == "__main__":
    main()
