import json
from gdr.models import Paper
from gdr.relevance import score_paper


def _paper():
    return Paper(id="arxiv:1", source="arxiv", title="Magnetar giant flare",
                 authors=[], abstract="A magnetar SGR burst.", categories=["astro-ph.HE"],
                 published="2026-07-18", url="")


def test_score_paper_parses_and_layers(fake_llm_factory):
    reply = json.dumps({"score": 92, "tags": ["磁星", "SGR"], "reason": "GECAM 核心主题"})
    llm = fake_llm_factory([reply])
    rs = score_paper(_paper(), llm)
    assert rs.score == 92
    assert rs.layer == "core"
    assert "磁星" in rs.tags
    assert llm.calls[0]["model"] != ""  # triage model used


def test_score_paper_bad_output_is_safe_edge(fake_llm_factory):
    llm = fake_llm_factory(["not json at all"])
    rs = score_paper(_paper(), llm)
    assert rs.layer == "edge"
    assert rs.score == 0


def test_score_clamped(fake_llm_factory):
    llm = fake_llm_factory([json.dumps({"score": 150, "tags": [], "reason": "x"})])
    assert score_paper(_paper(), llm).score == 100
