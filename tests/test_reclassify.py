import json

from gdr.models import DailyReview, DayData, Paper, PaperSummary, RelevanceScore
from gdr.reclassify import reclassify_day
from gdr.store import Store


def test_reclassify_reuses_items_and_regenerates_headline(tmp_path, fake_llm_factory):
    store = Store(tmp_path / "data")
    paper = Paper("arxiv:1", "arxiv", "A TDE flare", [], "X-ray transient flare", [],
                  "2026-07-21", "https://arxiv.org/abs/1")
    old_review = DailyReview("2026-07-21", "旧概览", "", "")
    store.save_day(DayData("2026-07-21", old_review, [{
        "paper": paper, "score": RelevanceScore(75, ["TDE"], "core", "旧规则"),
        "summary": PaperSummary("arxiv:1", "TDE耀发", "", "研究X射线耀发", "",
                                "给出耀发观测", ""),
    }]))
    llm = fake_llm_factory({
        "主题标签与相关层级是两个独立判断": json.dumps({
            "layer": "related", "score": 88, "tags": ["TDE"],
            "relation": "enabling", "core_path": "", "evidence": "研究总体率",
            "reason": "范围内的间接支撑",
        }),
    })

    result = reclassify_day("2026-07-21", store, llm, synced="2026-07-22", max_workers=1)

    day = store.load_day("2026-07-21")
    assert result == {"updated": 1, "failed": 0, "core": 0, "related": 1, "edge": 0}
    assert day.items[0]["score"].layer == "related"
    assert day.review.editorial_version == 2
    assert day.review.stories == []
    assert day.revisions[0]["review"]["overview"] == "旧概览"
