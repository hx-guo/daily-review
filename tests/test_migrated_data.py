"""Acceptance checks on the real migrated data. These run against data/ in the
repository, not a fixture — they are the migration's proof, not unit tests."""
import json
from pathlib import Path

import pytest

from gdr.store import Store

ROOT = Path(__file__).resolve().parent.parent
DAILY = ROOT / "data" / "daily"
INGEST = ROOT / "data" / "ingest"

pytestmark = pytest.mark.skipif(not INGEST.exists(),
                                reason="migration has not run yet")


def _legacy_days():
    return [json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(DAILY.glob("*.json"))]


def test_every_paper_survived_the_migration():
    if not DAILY.exists():
        pytest.skip("legacy data already removed")
    before = {it["paper"]["id"] for day in _legacy_days() for it in day["items"]}
    after = {it["paper"].id for it in Store(ROOT / "data").all_items()}

    assert after == before


def test_every_item_has_an_ingest_date_and_an_archive_date():
    for item in Store(ROOT / "data").all_items():
        assert item["dates"]["ingested"], item["paper"].id
        assert item["archive_date"], item["paper"].id


def test_retained_stories_match_the_pre_migration_review():
    """Migration moves each paper to its true earliest academic date, which
    can shift it off the day it was reviewed on (e.g. a paper filed under one
    ingest day but carrying an arXiv v1 date months earlier now archives
    under that earlier date). So per-day story counts can't survive the
    migration intact — what has to survive is which papers were retained as
    stories, and at what level, regardless of which day they land on."""
    if not DAILY.exists():
        pytest.skip("legacy data already removed")
    before = {s["paper_id"]: s["level"]
              for day in _legacy_days() for s in day["review"].get("stories", [])}
    after = {it["paper"].id: it["decision"]["level"]
             for it in Store(ROOT / "data").all_items()
             if it.get("decision") and it["decision"]["level"] != "reject"}

    assert after == before


def test_ingest_days_are_not_in_the_future_of_their_papers():
    for item in Store(ROOT / "data").all_items():
        assert item["dates"]["ingested"] >= item["archive_date"], item["paper"].id
