import argparse
import datetime as dt
from pathlib import Path
from gdr import config
from gdr.llm import OpenCodeLLM
from gdr.sources.ads_source import ADSSource
from gdr.sources.arxiv_source import ArxivSource
from gdr.sources.composite_source import CompositeSource
from gdr.store import Store
from gdr.pipeline import sync
from gdr.render import render_site

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="YYYY-MM-DD window end (default: today UTC)")
    args = ap.parse_args()
    date = args.date or dt.datetime.now(dt.timezone.utc).date().isoformat()

    llm = OpenCodeLLM(api_key=config.get_api_key())
    sources = [ArxivSource(categories=config.ARXIV_CATEGORIES)]
    ads_token = config.get_ads_token()
    if ads_token:
        sources.append(ADSSource(token=ads_token))
    else:
        print("[gdr] ADS_API_TOKEN is not set; continuing with arXiv only")
    source = CompositeSource(sources)
    store = Store(ROOT / "data")

    affected = sync(date, source, llm, store)
    print(f"{date}: synced; affected dates: {affected}")
    render_site(store, ROOT / "site", ROOT / "templates", ROOT / "static")


if __name__ == "__main__":
    main()
