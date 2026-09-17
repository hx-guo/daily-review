import argparse
import datetime as dt
import sys
from pathlib import Path
from gdr import config
from gdr.llm import make_llm
from gdr.sources.ads_source import ADSSource
from gdr.sources.arxiv_source import ArxivSource
from gdr.sources.composite_source import CompositeSource
from gdr.store import Store
from gdr.pipeline import PartialFailure, repair_decisions, sync
from gdr.site_build import build_site

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="YYYY-MM-DD window end (default: today UTC)")
    args = ap.parse_args()
    date = args.date or dt.datetime.now(dt.timezone.utc).date().isoformat()

    llm = make_llm()
    sources = [ArxivSource(categories=config.ARXIV_CATEGORIES)]
    ads_token = config.get_ads_token()
    if ads_token:
        sources.append(ADSSource(token=ads_token))
    else:
        print("[gdr] ADS_API_TOKEN is not set; continuing with arXiv only")
    source = CompositeSource(sources)
    store = Store(ROOT / "data")

    repair_decisions(store, llm)
    partial = None
    try:
        affected = sync(date, source, llm, store)
    except PartialFailure as exc:
        # The survivors are already on disk. Render and commit them as usual,
        # then end the run red -- a day that quietly lost most of its papers is
        # exactly what went unnoticed on 2026-09-16.
        partial, affected = exc, exc.dates
        print(f"[gdr] {exc}", file=sys.stderr)
    print(f"{date}: synced; affected dates: {affected}")
    build_site(ROOT)
    if partial is not None:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
