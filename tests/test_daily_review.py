import json
import re

from gdr import config
from gdr.daily_review import Breaker, review_paper
from gdr.models import Paper, PaperSummary, RelevanceScore, make_item


def _item(pid="arxiv:1", layer="core", *, title=None, authors=None, abstract=None,
          doi=None, preprint="2026-03-12", ingested="2026-07-18"):
    paper = Paper(
        id=pid, source="arxiv", title=title or f"paper {pid}",
        authors=authors if authors is not None else ["A. Researcher"],
        abstract=abstract if abstract is not None else
        "We report a directly measured transient result with quantitative evidence.",
        categories=[], published=preprint, url="", doi=doi)
    score = RelevanceScore(score=90, tags=["GRB"], layer=layer, reason="直接研究GRB")
    summary = PaperSummary(paper_id=pid, title_zh=f"伽马暴研究 {pid}", team="",
                           tldr="研究了伽马暴", review="", highlight="给出首次观测",
                           relation="")
    return make_item(paper, score, summary,
                     dates={"preprint": preprint, "ingested": ingested})


def _candidate(pid, decision="headline"):
    return json.dumps({"paper_id": pid, "decision": decision,
                       "reason": "摘要给出可能达到新闻门槛的具体结果。"})


def _verified(pid, decision="headline", watchlist=None):
    retained = decision != "reject"
    return json.dumps({
        "paper_id": pid, "decision": decision,
        "title": f"重大进展 {pid}" if retained else "",
        "evidence": "摘要报告了具体的新观测结果。" if retained else "",
        "impact": "改变了对爆发机制的认识。" if retained else "",
        "reason": "结果通过严格复核。" if retained else "未达到重大新闻门槛。",
        "watchlist": watchlist if watchlist is not None else (
            ["等待独立确认"] if retained else []),
    })


def test_review_paper_runs_two_passes_on_a_single_paper(fake_llm_factory):
    llm = fake_llm_factory([_candidate("arxiv:1", "breaking"),
                           _verified("arxiv:1", "breaking")])

    decision = review_paper(_item(), llm)

    assert decision["level"] == "breaking"
    assert decision["title"] == "重大进展 arxiv:1"
    assert decision["reviewed_at"] == "2026-07-18"
    assert len(llm.calls) == 2
    assert "不选择主头条" in llm.calls[0]["user"]
    assert "第二位、更加怀疑" in llm.calls[1]["user"]


def test_prompt_carries_the_papers_own_preprint_and_ingest_dates(fake_llm_factory):
    """The decision is cached forever, so it must not depend on "today"."""
    llm = fake_llm_factory([_candidate("arxiv:1"), _verified("arxiv:1")])

    review_paper(_item(preprint="2026-03-12", ingested="2026-07-18"), llm)

    assert "本文预印本日 2026-03-12" in llm.calls[0]["user"]
    assert "本站于 2026-07-18 收录" in llm.calls[0]["user"]
    assert "今天是" not in llm.calls[0]["user"]


def test_rejected_paper_yields_a_reject_decision_not_none(fake_llm_factory):
    llm = fake_llm_factory([_candidate("arxiv:1", "reject")])

    decision = review_paper(_item(), llm)

    assert decision["level"] == "reject"
    assert decision["title"] == ""
    assert len(llm.calls) == 1


def test_watchlist_signals_carry_their_own_paper_id(fake_llm_factory):
    llm = fake_llm_factory([
        _candidate("arxiv:1"),
        _verified("arxiv:1", watchlist=["等待独立确认",
                                        "（arxiv:9999.99999）另一路信号需后随观测"])])

    decision = review_paper(_item(), llm)

    assert decision["watchlist"] == ["等待独立确认（arxiv:1）",
                                     "另一路信号需后随观测（arxiv:1）"]


def test_edge_and_non_research_papers_are_never_sent_to_the_model(fake_llm_factory):
    llm = fake_llm_factory([])

    assert review_paper(_item(layer="edge"), llm, sleep=lambda s: None) is None
    assert review_paper(_item(title="Publisher Correction: A result"), llm,
                        sleep=lambda s: None) is None
    assert review_paper(_item(authors=[], abstract="A short editorial blurb."),
                        llm, sleep=lambda s: None) is None
    assert llm.calls == []


def test_nine_bad_responses_then_a_good_one_still_succeeds(fake_llm_factory):
    llm = fake_llm_factory(["not json"] * 9 + [_candidate("arxiv:1", "reject")])
    slept = []

    decision = review_paper(_item(), llm, sleep=slept.append)

    assert decision["level"] == "reject"
    assert len(llm.calls) == 10
    assert slept == list(config.EDITORIAL_BACKOFF)


def test_ten_bad_responses_give_up_and_return_none(fake_llm_factory):
    llm = fake_llm_factory(["not json"] * 10)

    assert review_paper(_item(), llm, sleep=lambda s: None) is None
    assert len(llm.calls) == 10


def test_wrong_schema_is_retried_rather_than_becoming_a_false_reject(fake_llm_factory):
    llm = fake_llm_factory([json.dumps({"candidates": []}),
                            _candidate("arxiv:1"), _verified("arxiv:1")])

    decision = review_paper(_item(), llm, sleep=lambda s: None)

    assert decision["level"] == "headline"
    assert "不要为了修复格式而降低门槛" in llm.calls[1]["user"]


def test_verification_cannot_upgrade_a_headline_to_breaking(fake_llm_factory):
    llm = fake_llm_factory([_candidate("arxiv:1", "headline")]
                           + [_verified("arxiv:1", "breaking")] * 10)

    assert review_paper(_item(), llm, sleep=lambda s: None) is None
    assert len(llm.calls) == 11


def test_breaker_trips_after_twenty_consecutive_total_failures(fake_llm_factory):
    breaker = Breaker(limit=2)
    llm = fake_llm_factory(["not json"] * 20)

    assert review_paper(_item("arxiv:1"), llm, breaker=breaker,
                        sleep=lambda s: None) is None
    assert review_paper(_item("arxiv:2"), llm, breaker=breaker,
                        sleep=lambda s: None) is None
    assert breaker.tripped()

    before = len(llm.calls)
    assert review_paper(_item("arxiv:3"), llm, breaker=breaker,
                        sleep=lambda s: None) is None
    assert len(llm.calls) == before          # tripped: no further calls at all


def test_one_success_resets_the_breaker(fake_llm_factory):
    breaker = Breaker(limit=2)
    llm = fake_llm_factory(["not json"] * 10 + [_candidate("arxiv:2", "reject")])

    review_paper(_item("arxiv:1"), llm, breaker=breaker, sleep=lambda s: None)
    review_paper(_item("arxiv:2"), llm, breaker=breaker, sleep=lambda s: None)

    assert not breaker.tripped()


def test_a_failed_paper_is_logged_to_stderr_with_its_id(fake_llm_factory, capsys):
    """A dead upstream must show up in the log, not just as a silent decision=None
    (the exact incident config.py's EDITORIAL_ATTEMPTS comment cites)."""
    llm = fake_llm_factory(["not json"] * 10)

    assert review_paper(_item("arxiv:42"), llm, sleep=lambda s: None) is None

    assert "arxiv:42" in capsys.readouterr().err
