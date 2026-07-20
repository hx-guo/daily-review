import json
from gdr.models import Paper
from gdr.summarize import summarize_paper

def _paper():
    return Paper(id="arxiv:1", source="arxiv", title="Magnetar giant flare",
                 authors=["Alice Author"], abstract="A magnetar SGR burst.",
                 categories=["astro-ph.HE"], published="2026-07-18", url="")

def test_summarize_uses_fulltext_and_parses(fake_llm_factory):
    reply = json.dumps({
        "title_zh": "磁星巨耀发", "tldr": "研究一次磁星巨耀发",
        "highlight": "首次……",
        "context_outlook": "承接 [[Kaspi+ 2017]] 的磁星综述，展望 GW 时代的多信使跟踪。",
        "citations": [{"label": "Kaspi+ 2017", "arxiv": "1703.00068", "doi": ""}],
        "authors_en": "Alice Author (MIT)", "corresponding_en": "Alice Author",
    })
    llm = fake_llm_factory([reply])
    s = summarize_paper(_paper(), fulltext="FULL BODY TEXT", llm=llm)
    assert s.title_zh == "磁星巨耀发"
    assert s.paper_id == "arxiv:1"
    assert "FULL BODY TEXT" in llm.calls[0]["user"]
    assert s.authors_en == "Alice Author (MIT)"
    assert s.corresponding_en == "Alice Author"
    assert "[[Kaspi+ 2017]]" in s.context_outlook
    assert s.citations == [{"label": "Kaspi+ 2017", "arxiv": "1703.00068", "doi": ""}]
    # deprecated card fields are no longer generated
    assert s.review == "" and s.relation == "" and s.team == ""

def test_summarize_drops_bad_citations(fake_llm_factory):
    reply = json.dumps({
        "title_zh": "x", "tldr": "t", "highlight": "h", "context_outlook": "c",
        "citations": [{"label": "Good+ 2020", "arxiv": "1", "doi": ""},
                      {"label": ""}, "not-a-dict", {"arxiv": "9"}],
    })
    s = summarize_paper(_paper(), fulltext="B", llm=fake_llm_factory([reply]))
    assert s.citations == [{"label": "Good+ 2020", "arxiv": "1", "doi": ""}]

def test_summarize_falls_back_to_abstract(fake_llm_factory):
    llm = fake_llm_factory([json.dumps({"title_zh": "x", "tldr": "",
                                        "highlight": "", "context_outlook": ""})])
    summarize_paper(_paper(), fulltext=None, llm=llm)
    assert "A magnetar SGR burst." in llm.calls[0]["user"]

def test_summarize_bad_output_uses_metadata(fake_llm_factory):
    llm = fake_llm_factory(["garbage"])
    s = summarize_paper(_paper(), fulltext=None, llm=llm)
    assert s.title_zh == "Magnetar giant flare"
    assert s.context_outlook == "A magnetar SGR burst."   # abstract kept as outlook fallback
    assert s.review == ""
    assert s.authors_en == "" and s.corresponding_en == ""


def test_summarize_edge_light(fake_llm_factory):
    import json
    from gdr.summarize import summarize_edge
    llm = fake_llm_factory([json.dumps({"title_zh": "磁星巨耀发", "tldr": "研究一次磁星巨耀发"})])
    p = _paper()  # existing helper in this file (english title/abstract)
    s = summarize_edge(p, llm)
    assert s.title_zh == "磁星巨耀发"
    assert s.tldr == "研究一次磁星巨耀发"
    assert s.review == "" and s.team == ""            # light: no full fields
    assert p.abstract in llm.calls[0]["user"]         # from abstract, not full text


def test_summarize_edge_bad_output_falls_back(fake_llm_factory):
    from gdr.summarize import summarize_edge
    llm = fake_llm_factory(["garbage"])
    s = summarize_edge(_paper(), llm)
    assert s.title_zh == _paper().title               # falls back to english title, never crashes
    assert s.authors_en == "" and s.corresponding_en == ""
