"""Acceptance checks on the real stored data. These run against data/ in the
repository, not a fixture."""
from pathlib import Path

from gdr.store import Store

ROOT = Path(__file__).resolve().parent.parent


def test_every_item_has_an_ingest_date_and_an_archive_date():
    for item in Store(ROOT / "data").all_items():
        assert item["dates"]["ingested"], item["paper"].id
        assert item["archive_date"], item["paper"].id


def test_ingest_days_are_not_in_the_future_of_their_papers():
    for item in Store(ROOT / "data").all_items():
        assert item["dates"]["ingested"] >= item["archive_date"], item["paper"].id
