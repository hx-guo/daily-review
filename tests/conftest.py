from pathlib import Path

import pytest

from gdr.models import IngestDay, Paper, PaperSummary, RelevanceScore, make_item
from gdr.render import render_site
from gdr.store import Store


class FakeLLM:
    """Test double for gdr.llm.LLM. Returns queued or keyed responses."""

    def __init__(self, responses):
        self._responses = responses
        self._i = 0
        self.calls = []

    def complete(self, model, system, user, temperature=0.3):
        self.calls.append({"model": model, "system": system, "user": user})
        if isinstance(self._responses, dict):
            for key, val in self._responses.items():
                if key in user:
                    return val(user) if callable(val) else val
            raise AssertionError(f"no keyed FakeLLM response matched user prompt")
        resp = self._responses[self._i]
        self._i += 1
        return resp


@pytest.fixture
def fake_llm_factory():
    return lambda responses: FakeLLM(responses)


def _make_ritem(pid, *, archive, ingested, layer="core", score=90, decision=None):
    paper = Paper(id=pid, source="arxiv", title=f"Title {pid}", authors=["A. B."],
                  abstract="abstract", categories=["astro-ph.HE"],
                  published=archive, url=f"https://arxiv.org/abs/{pid}")
    rs = RelevanceScore(score=score, tags=["GRB"], layer=layer, reason="r")
    summary = PaperSummary(paper_id=pid, title_zh=f"中文 {pid}", team="", tldr="t",
                           review="", highlight="亮点", relation="")
    return make_item(paper, rs, summary,
                     dates={"preprint": archive, "ingested": ingested},
                     decision=decision)


def _make_story_decision(pid, level="headline"):
    return {"level": level, "title": f"头条 {pid}", "evidence": "证据",
            "impact": "影响", "reason": "依据", "watchlist": [f"信号（{pid}）"],
            "reviewed_at": "2026-07-22"}


@pytest.fixture
def ritem():
    return _make_ritem


@pytest.fixture
def story_decision():
    return _make_story_decision


@pytest.fixture
def build_site_from(tmp_path):
    """(ingest date, items) pairs -> a rendered site directory."""
    def build(ingest_days):
        store = Store(tmp_path / "data")
        for date, items in ingest_days:
            store.save_ingest(IngestDay(ingested=date, items=items))
        out = tmp_path / "site"
        render_site(store, out, Path("templates"), Path("static"))
        return out
    return build
