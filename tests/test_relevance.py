import json
from gdr.models import Paper
from gdr.relevance import score_paper


def _paper():
    return Paper(id="arxiv:1", source="arxiv", title="Magnetar giant flare",
                 authors=[], abstract="A magnetar SGR burst.", categories=["astro-ph.HE"],
                 published="2026-07-18", url="")


def test_score_paper_parses_and_layers(fake_llm_factory):
    reply = json.dumps({
        "layer": "core", "score": 92, "tags": ["磁星", "SGR"],
        "relation": "direct", "core_path": "science",
        "evidence": "摘要研究磁星巨耀发", "reason": "直接研究磁星爆发",
    })
    llm = fake_llm_factory([reply])
    rs = score_paper(_paper(), llm)
    assert rs.score == 92
    assert rs.layer == "core"
    assert "磁星" in rs.tags
    assert rs.relation == "direct"
    assert rs.core_path == "science"
    assert "巨耀发" in rs.evidence
    assert llm.calls[0]["model"] != ""  # triage model used


def test_explicit_layer_is_not_derived_from_priority_score(fake_llm_factory):
    reply = json.dumps({
        "layer": "related", "score": 95, "tags": ["TDE"],
        "relation": "enabling", "core_path": "", "evidence": "总体率预报",
        "reason": "属于范围内，但对团队目标是间接支撑",
    })
    rs = score_paper(_paper(), fake_llm_factory([reply]))
    assert rs.score == 95
    assert rs.layer == "related"


def test_inconsistent_core_without_direct_evidence_is_downgraded(fake_llm_factory):
    reply = json.dumps({
        "layer": "core", "score": 95, "tags": ["FRB"],
        "relation": "contextual", "core_path": "", "evidence": "仅把FRB作为例子",
        "reason": "背景提及",
    })
    rs = score_paper(_paper(), fake_llm_factory([reply]))
    assert rs.layer == "related"


def test_score_paper_bad_output_is_safe_edge(fake_llm_factory):
    llm = fake_llm_factory(["not json at all"])
    rs = score_paper(_paper(), llm)
    assert rs.layer == "edge"
    assert rs.score == 0


def test_score_clamped(fake_llm_factory):
    llm = fake_llm_factory([json.dumps({"layer": "core", "score": 150,
                                        "tags": [], "reason": "x"})])
    assert score_paper(_paper(), llm).score == 100
