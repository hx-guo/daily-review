import json

from gdr.models import IngestDay, Paper, PaperSummary, RelevanceScore, make_item
from gdr.reclassify import reclassify_day
from gdr.store import Store


def test_reclassify_rescores_without_touching_the_cached_decision(fake_llm_factory, tmp_path):
    store = Store(tmp_path / "data")
    paper = Paper("arxiv:1", "arxiv", "A TDE flare", [], "X-ray transient flare", [],
                  "2026-07-21", "https://arxiv.org/abs/1")
    decision = {"level": "headline", "title": "T", "evidence": "E", "impact": "I",
                "reason": "R", "watchlist": [], "reviewed_at": "2026-07-21"}
    item = make_item(paper, RelevanceScore(75, ["TDE"], "core", "旧规则"),
                     PaperSummary("arxiv:1", "TDE耀发", "", "研究X射线耀发", "",
                                 "给出耀发观测", ""),
                     dates={"preprint": "2026-07-21", "ingested": "2026-07-21"},
                     decision=decision)
    store.save_ingest(IngestDay(ingested="2026-07-21", items=[item]))
    llm = fake_llm_factory({
        "主题标签与相关层级是两个独立判断": json.dumps({
            "layer": "related", "score": 88, "tags": ["TDE"],
            "relation": "enabling", "core_path": "", "evidence": "研究总体率",
            "reason": "范围内的间接支撑",
        }),
    })

    result = reclassify_day("2026-07-21", store, llm, max_workers=1)

    day = store.load_ingest("2026-07-21")
    assert result == {"updated": 1, "failed": 0, "core": 0, "related": 1, "edge": 0}
    assert day.items[0]["score"].layer == "related"
    # The cached decision survives the rescore untouched — a rescore must never
    # wipe out an already-reviewed headline.
    assert day.items[0]["decision"]["level"] == "headline"
    assert day.items[0]["decision"]["title"] == "T"
