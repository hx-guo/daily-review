import json
import subprocess

from gdr.migrate import build_ingest_days, decisions_from_review, ingest_dates_from_git
from gdr.models import DailyReview, DayData, Paper, PaperSummary, RelevanceScore


def _git(repo, *args, date=None):
    env = {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date} if date else {}
    subprocess.run(["git", *args], cwd=repo, check=True,
                   capture_output=True, env={**_base_env(), **env})


def _base_env():
    import os
    return {**os.environ, "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@e",
            "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@e",
            "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}


def _write_day(repo, date, ids):
    path = repo / "data" / "daily" / f"{date}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "date": date,
        "review": {"date": date, "overview": "o", "highlights": "", "trends": "",
                   "editorial_version": 2, "stories": [], "watchlist": []},
        "items": [{"paper": {"id": pid, "source": "arxiv", "title": "t",
                             "authors": [], "abstract": "a", "categories": [],
                             "published": "2026-07-14", "url": "",
                             "pdf_url": None, "doi": None, "external_ids": {}},
                   "score": {"score": 90, "tags": [], "layer": "core",
                             "reason": "r", "relation": "", "core_path": "",
                             "evidence": ""},
                   "summary": None} for pid in ids],
        "revisions": [],
    }, ensure_ascii=False), encoding="utf-8")


def test_ingest_dates_come_from_the_commit_that_first_introduced_each_paper(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _write_day(repo, "2026-07-14", ["arxiv:1", "arxiv:2"])
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "first", date="2026-07-18T10:00:00 +0000")
    _write_day(repo, "2026-07-14", ["arxiv:1", "arxiv:2", "arxiv:3"])
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "backfill", date="2026-07-21T10:00:00 +0000")

    got = ingest_dates_from_git(repo)

    assert got == {"arxiv:1": "2026-07-18", "arxiv:2": "2026-07-18",
                   "arxiv:3": "2026-07-21"}


def _day_with_story():
    paper = Paper(id="arxiv:1", source="arxiv", title="t", authors=["A"],
                  abstract="a", categories=[], published="2026-07-14", url="")
    other = Paper(id="arxiv:2", source="arxiv", title="t2", authors=["A"],
                  abstract="a", categories=[], published="2026-07-14", url="")
    score = RelevanceScore(score=90, tags=[], layer="core", reason="r")
    edge = RelevanceScore(score=10, tags=[], layer="edge", reason="r")
    summary = PaperSummary(paper_id="arxiv:1", title_zh="标题", team="", tldr="t",
                           review="", highlight="h", relation="")
    review = DailyReview(
        date="2026-07-14", overview="o", highlights="", trends="",
        editorial_version=2,
        stories=[{"paper_id": "arxiv:1", "level": "breaking", "title": "T",
                  "evidence": "E", "impact": "I", "reason": "R"}],
        watchlist=["信号一（arxiv:1）", "无标识的信号"])
    return DayData(date="2026-07-14", review=review, items=[
        {"paper": paper, "score": score, "summary": summary},
        {"paper": other, "score": edge, "summary": None}])


def test_decisions_are_recovered_from_stories_and_the_rest_marked_rejected():
    day = _day_with_story()
    day.items.append({"paper": Paper(id="arxiv:3", source="arxiv", title="t3",
                                     authors=["A"], abstract="a", categories=[],
                                     published="2026-07-14", url=""),
                      "score": RelevanceScore(80, [], "related", "r"),
                      "summary": None})

    got = decisions_from_review(day)

    assert got["arxiv:1"]["level"] == "breaking"
    assert got["arxiv:1"]["impact"] == "I"
    assert got["arxiv:3"]["level"] == "reject"
    assert got["arxiv:3"]["reason"] == "迁移：v2 复核未入选"
    assert "arxiv:2" not in got                     # edge papers are never reviewed


def test_watchlist_without_an_id_goes_to_the_only_story_of_that_day():
    got = decisions_from_review(_day_with_story())

    assert got["arxiv:1"]["watchlist"] == ["信号一（arxiv:1）", "无标识的信号（arxiv:1）"]


def test_build_ingest_days_groups_by_ingest_date_and_computes_archive_date():
    day = _day_with_story()
    ingest = {"arxiv:1": "2026-07-18", "arxiv:2": "2026-07-21"}

    out = {d.ingested: d for d in build_ingest_days(
        [day], ingest,
        resolve_dates=lambda paper, ingested: {
            "preprint": "2026-07-14", "accepted": "", "published": "",
            "published_precision": "", "published_source": "", "received": "",
            "ingested": ingested})}

    assert sorted(out) == ["2026-07-18", "2026-07-21"]
    assert [it["paper"].id for it in out["2026-07-18"].items] == ["arxiv:1"]
    assert out["2026-07-18"].items[0]["archive_date"] == "2026-07-14"
    assert out["2026-07-18"].items[0]["decision"]["level"] == "breaking"
    assert out["2026-07-21"].items[0]["decision"] is None       # edge
