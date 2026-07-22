import json
import re
import threading
import time

from gdr.daily_review import make_daily_review
from gdr.models import Paper, PaperSummary, RelevanceScore


def _item(pid="arxiv:1", layer="core", *, title=None, authors=None,
          abstract=None, doi=None):
    paper = Paper(
        id=pid, source="arxiv", title=title or f"paper {pid}",
        authors=authors if authors is not None else ["A. Researcher"],
        abstract=abstract if abstract is not None else
        "We report a directly measured transient result with quantitative evidence.",
        categories=[], published="2026-07-18", url="", doi=doi,
    )
    score = RelevanceScore(score=90, tags=["GRB"], layer=layer, reason="直接研究GRB")
    summary = PaperSummary(paper_id=pid, title_zh=f"伽马暴研究 {pid}", team="",
                           tldr="研究了伽马暴", review="", highlight="给出首次观测", relation="")
    return {"paper": paper, "score": score, "summary": summary}


def _candidate(pid, decision="headline"):
    return {
        "paper_id": pid,
        "decision": decision,
        "reason": "摘要给出可能达到新闻门槛的具体结果。",
    }


def _verified(pid, decision="headline"):
    retained = decision != "reject"
    return {
        "paper_id": pid,
        "decision": decision,
        "title": f"重大进展 {pid}" if retained else "",
        "evidence": "摘要报告了具体的新观测结果。" if retained else "",
        "impact": "改变了对爆发机制的认识。" if retained else "",
        "reason": "结果通过严格复核。" if retained else "未达到重大新闻门槛。",
        "watchlist": ["等待独立确认"] if retained else [],
    }


def test_make_daily_review_uses_two_passes_and_equal_stories(fake_llm_factory):
    llm = fake_llm_factory([
        json.dumps(_candidate("arxiv:1", "breaking")),
        json.dumps(_verified("arxiv:1", "breaking")),
    ])

    review = make_daily_review("2026-07-18", [_item()], llm)

    assert review.editorial_version == 2
    assert review.stories[0]["level"] == "breaking"
    assert review.stories[0]["paper_id"] == "arxiv:1"
    assert review.headline == "" and review.headline_paper_id == ""
    assert len(llm.calls) == 2
    assert "不选择主头条" in llm.calls[0]["user"]
    assert "不选主头条" in llm.calls[1]["user"]


def test_story_count_has_no_editorial_cap(fake_llm_factory):
    items = [_item(f"arxiv:{i}") for i in range(6)]
    levels = ["breaking" if i % 2 else "headline" for i in range(6)]
    llm = fake_llm_factory([
        *[json.dumps(_candidate(f"arxiv:{i}", levels[i])) for i in range(6)],
        *[json.dumps(_verified(f"arxiv:{i}", levels[i])) for i in range(6)],
    ])

    review = make_daily_review(
        "2026-07-18", items, llm, editorial_workers=1)

    assert len(review.stories) == 6
    assert len(llm.calls) == 12


def test_verifier_only_receives_nominated_paper(fake_llm_factory):
    nominated = _item("arxiv:nominated", title="NOMINATED SOURCE TITLE")
    ordinary = _item("arxiv:ordinary", title="ORDINARY SOURCE TITLE")
    llm = fake_llm_factory([
        json.dumps(_candidate("arxiv:nominated")),
        json.dumps(_candidate("arxiv:ordinary", "reject")),
        json.dumps(_verified("arxiv:nominated")),
    ])

    make_daily_review(
        "2026-07-18", [nominated, ordinary], llm, editorial_workers=1)

    assert "NOMINATED SOURCE TITLE" in llm.calls[2]["user"]
    assert "ORDINARY SOURCE TITLE" not in llm.calls[2]["user"]


def test_malformed_json_is_retried_without_lowering_threshold(fake_llm_factory):
    llm = fake_llm_factory([
        "not valid json",
        json.dumps(_candidate("arxiv:1")),
        json.dumps(_verified("arxiv:1")),
    ])

    review = make_daily_review("2026-07-18", [_item()], llm)

    assert [item["paper_id"] for item in review.stories] == ["arxiv:1"]
    assert len(llm.calls) == 3
    assert "不要为了修复格式而降低门槛" in llm.calls[1]["user"]


def test_wrong_json_schema_is_retried_instead_of_becoming_false_zero(
        fake_llm_factory):
    llm = fake_llm_factory([
        json.dumps({"candidates": []}),
        json.dumps(_candidate("arxiv:1")),
        json.dumps(_verified("arxiv:1")),
    ])

    review = make_daily_review("2026-07-18", [_item()], llm)

    assert [item["paper_id"] for item in review.stories] == ["arxiv:1"]
    assert len(llm.calls) == 3


def test_two_malformed_responses_return_failure_review(fake_llm_factory):
    llm = fake_llm_factory(["not json", "still not json"])

    review = make_daily_review("2026-07-18", [_item()], llm)

    assert review.stories == []
    assert review.overview == "新闻候选复核生成失败。"


def test_invalid_or_incomplete_verified_story_fails_closed(fake_llm_factory):
    incomplete = _verified("arxiv:1")
    incomplete["evidence"] = ""
    llm = fake_llm_factory([
        json.dumps(_candidate("arxiv:1")),
        json.dumps(incomplete),
        json.dumps(incomplete),
    ])

    review = make_daily_review("2026-07-18", [_item()], llm)

    assert review.stories == []
    assert review.overview == "新闻候选复核生成失败。"


def test_secondary_nature_briefing_cannot_become_story(fake_llm_factory):
    briefing_id = "ads:2026Natur.655R.285."
    briefing = _item(
        briefing_id,
        title="Neutrino's nursery found: the `Shadow Blaster'",
        authors=[],
        abstract="A particle detected at the South Pole was born in a distant galaxy.",
        doi="10.1038/d41586-026-02034-1",
    )
    original = _item("arxiv:original")
    llm = fake_llm_factory([
        json.dumps(_candidate("arxiv:original")),
        json.dumps(_verified("arxiv:original")),
    ])

    review = make_daily_review(
        "2026-07-18", [briefing, original], llm, editorial_workers=1)

    assert [story["paper_id"] for story in review.stories] == ["arxiv:original"]
    assert briefing_id not in llm.calls[0]["user"]
    assert "原文摘要" in llm.calls[0]["user"]
    assert "不能独立作为新闻证据" in llm.calls[0]["user"]


def test_both_per_paper_editorial_passes_run_concurrently():
    class ConcurrentLLM:
        def __init__(self):
            self.active = {"nominate": 0, "verify": 0}
            self.max_active = {"nominate": 0, "verify": 0}
            self.lock = threading.Lock()

        def complete(self, model, system, user, temperature=0.3):
            paper_id = re.search(r"paper_id=([^ ]+)", user).group(1)
            phase = "verify" if "第二位、更加怀疑" in user else "nominate"
            with self.lock:
                self.active[phase] += 1
                self.max_active[phase] = max(
                    self.max_active[phase], self.active[phase])
            time.sleep(0.03)
            with self.lock:
                self.active[phase] -= 1
            response = (_verified(paper_id) if phase == "verify"
                        else _candidate(paper_id))
            return json.dumps(response)

    llm = ConcurrentLLM()
    items = [_item(f"arxiv:{i}") for i in range(8)]

    review = make_daily_review(
        "2026-07-18", items, llm, editorial_workers=8)

    assert len(review.stories) == 8
    assert llm.max_active["nominate"] >= 4
    assert llm.max_active["verify"] >= 4


def test_correction_and_unbylined_blurb_skip_news_review(fake_llm_factory):
    llm = fake_llm_factory([])
    correction = _item("ads:correction", title="Publisher Correction: A result")
    blurb = _item("ads:blurb", authors=[], abstract="A short editorial blurb.")

    review = make_daily_review("2026-07-18", [correction, blurb], llm)

    assert review.stories == []
    assert llm.calls == []
    assert "原始研究" in review.overview


def test_empty_day_skips_llm(fake_llm_factory):
    llm = fake_llm_factory([])
    review = make_daily_review("2026-07-18", [], llm)
    assert review.date == "2026-07-18"
    assert llm.calls == []
    assert "无新文献" in review.overview
    assert review.editorial_version == 2
    assert review.stories == []
