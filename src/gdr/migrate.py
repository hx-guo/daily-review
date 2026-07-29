"""One-shot migration from date-keyed day files to ingest-keyed files.

The ingest date of every already-stored paper is recovered exactly from git: a
paper's ingest day is the date of the commit that first introduced its id. That
beats reconstructing from append order plus `revisions[].n_papers`, because
`reclassify_day()` also appends a revision without adding papers.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from gdr.models import DayData, IngestDay, make_item

_WATCH_ID_RE = re.compile(r"[（(\[]\s*(?:arxiv|ads):[^）)\]]+\s*[）)\]]",
                          re.IGNORECASE)


def _run(repo_root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo_root, check=True,
                          capture_output=True, text=True).stdout


def _run_soft(repo_root: Path, *args: str) -> str | None:
    """Like `_run`, but returns None instead of raising on a non-zero exit.

    Used only for the two lookups where a failure is an expected outcome of
    real history, not a real error: `ls-tree` on `data/daily` at a commit
    where the directory doesn't exist (e.g. its last file was deleted there —
    git doesn't track empty directories, so the path just vanishes from the
    tree), and `show` on a listed name that turns out not to be a blob. Every
    other git call in this module keeps `_run`'s hard failure.
    """
    result = subprocess.run(["git", *args], cwd=repo_root,
                            capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else None


def ingest_dates_from_git(repo_root: Path) -> dict[str, str]:
    """paper id -> the date of the commit that first stored it."""
    repo_root = Path(repo_root)
    log = _run(repo_root, "log", "--reverse", "--format=%H %cd", "--date=short",
               "--", "data/daily")
    first_seen: dict[str, str] = {}
    for line in log.splitlines():
        if not line.strip():
            continue
        sha, date = line.split(None, 1)
        names = _run_soft(repo_root, "ls-tree", "--name-only", f"{sha}:data/daily")
        if names is None:
            continue  # data/daily didn't exist at this commit
        for name in names.split():
            if not name.endswith(".json"):
                continue
            blob = _run_soft(repo_root, "show", f"{sha}:data/daily/{name}")
            if blob is None:
                continue  # listed name isn't a readable blob at this commit
            try:
                payload = json.loads(blob)
            except ValueError:
                continue
            for item in payload.get("items", []):
                pid = item.get("paper", {}).get("id", "")
                if pid and pid not in first_seen:
                    first_seen[pid] = date.strip()
    return first_seen


def decisions_from_review(day: DayData) -> dict[str, dict]:
    """Recover per-paper decisions from a stored day's `stories`.

    Papers that made the cut keep their full editorial text. Every other
    core/related paper was reviewed and rejected at the time — recorded as such
    rather than re-run, because that judgement is a historical fact and rerunning
    it would cost hundreds of calls.

    Does not set `reviewed_at`: this function only sees the paper's archive
    day, but the online path (daily_review.py) records the paper's INGEST
    date there. `build_ingest_days` fills it in once the ingest date is known.
    """
    stories = {s["paper_id"]: s for s in (day.review.stories or [])}
    watchlists: dict[str, list[str]] = {pid: [] for pid in stories}
    for signal in (day.review.watchlist or []):
        match = _WATCH_ID_RE.search(signal)
        if match:
            # The signal names its paper explicitly (see `_watch_signal` in
            # daily_review.py: the id is always the paper under review, never
            # guessed from the model's text). Honour that or drop the signal —
            # never reassign it to a different paper, even one that is the
            # day's only story.
            owner = match.group(0).strip("（）()[] ")
            if owner not in watchlists:
                continue
        else:
            # No id at all: the only sensible owner is the day's lone story.
            owner = next(iter(watchlists)) if len(watchlists) == 1 else ""
        if not owner:
            continue
        text = _WATCH_ID_RE.sub("", signal).strip(" 　·:：、，,；;")
        watchlists[owner].append(f"{text}（{owner}）")

    decisions: dict[str, dict] = {}
    for item in day.items:
        pid = item["paper"].id
        if item["score"].layer not in ("core", "related"):
            continue
        story = stories.get(pid)
        if story:
            decisions[pid] = {
                "level": story["level"], "title": story["title"],
                "evidence": story["evidence"], "impact": story["impact"],
                "reason": story["reason"],
                "watchlist": watchlists.get(pid, []),
            }
        else:
            decisions[pid] = {
                "level": "reject", "title": "", "evidence": "", "impact": "",
                "reason": "迁移：v2 复核未入选", "watchlist": [],
            }
    return decisions


def build_ingest_days(days: list[DayData], ingest_dates: dict[str, str],
                      resolve_dates) -> list[IngestDay]:
    """Regroup every stored paper under its ingest date, carrying its recovered
    decision and its freshly resolved four dates."""
    buckets: dict[str, list[dict]] = {}
    for day in days:
        decisions = decisions_from_review(day)
        for item in day.items:
            paper = item["paper"]
            ingested = ingest_dates.get(paper.id, day.date)
            decision = decisions.get(paper.id)
            if decision is not None:
                # Matches the online path (daily_review.py): the decision was
                # made on the day the paper was ingested and reviewed, not on
                # whatever day its own archive date happens to fall on.
                decision = {**decision, "reviewed_at": ingested}
            buckets.setdefault(ingested, []).append(
                make_item(paper, item["score"], item["summary"],
                          dates=resolve_dates(paper, ingested),
                          decision=decision))
    return [IngestDay(ingested=date, items=sorted(items,
                                                  key=lambda it: it["paper"].id))
            for date, items in sorted(buckets.items())]
