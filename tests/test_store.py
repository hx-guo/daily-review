import json

from gdr.models import Paper, RelevanceScore, IngestDay, make_item
from gdr.store import Store, _SEEN_IDENTITY_SCHEMA


def test_mark_seen_returns_new_only(tmp_path):
    st = Store(tmp_path)
    assert st.mark_seen_papers(["arxiv:1", "arxiv:2"]) == ["arxiv:1", "arxiv:2"]
    assert st.mark_seen_papers(["arxiv:2", "arxiv:3"]) == ["arxiv:3"]


def test_unseen_ids_is_readonly(tmp_path):
    st = Store(tmp_path)
    assert st.unseen_ids(["a", "b"]) == ["a", "b"]
    assert st.unseen_ids(["a", "b"]) == ["a", "b"]      # not persisted
    assert st.mark_seen_papers(["a"]) == ["a"]           # 'a' was genuinely new
    assert st.unseen_ids(["a", "b"]) == ["b"]


def test_identities_unseen_matches_any_alias(tmp_path):
    st = Store(tmp_path)
    st.mark_seen_papers(["arxiv:2607.1"])
    assert not st.identities_unseen({"ads:bib", "arxiv:2607.1", "doi:10.1/x"})
    assert st.identities_unseen({"ads:new", "doi:10.1/new"})


def test_ensure_seen_identities_backfills_legacy_ingest_papers(tmp_path):
    st = Store(tmp_path)
    paper = Paper(id="arxiv:1", source="arxiv", title="A Legacy GRB Paper", authors=[],
                 abstract="", categories=[], published="2026-07-18", url="",
                 doi="10.1/legacy")
    score = RelevanceScore(score=90, tags=["GRB"], layer="core", reason="")
    item = make_item(paper, score, None, dates={"ingested": "2026-07-18"})
    st.save_ingest(IngestDay(ingested="2026-07-18", items=[item]))
    st.mark_seen_papers([paper.id])  # old index format only kept the primary ID

    st.ensure_seen_identities()

    assert not st.identities_unseen({"doi:10.1/legacy"})
    assert not st.identities_unseen({"title:a legacy grb paper"})


def _ing_item(pid, ingested="2026-07-22", layer="core"):
    paper = Paper(id=pid, source="arxiv", title="t", authors=["A"], abstract="a",
                  categories=[], published="2026-07-20", url="")
    score = RelevanceScore(score=90, tags=[], layer=layer, reason="r")
    return make_item(paper, score, None,
                     dates={"preprint": "2026-07-20", "ingested": ingested})


def test_save_and_load_ingest_day(tmp_path):
    store = Store(tmp_path / "data")
    store.save_ingest(IngestDay(ingested="2026-07-22", items=[_ing_item("arxiv:1")]))

    back = store.load_ingest("2026-07-22")

    assert back.ingested == "2026-07-22"
    assert back.items[0]["paper"].id == "arxiv:1"
    assert (tmp_path / "data" / "ingest" / "2026-07-22.json").exists()


def test_list_ingest_dates_is_ascending_and_all_items_follows_it(tmp_path):
    store = Store(tmp_path / "data")
    store.save_ingest(IngestDay("2026-07-23", [_ing_item("arxiv:2", "2026-07-23")]))
    store.save_ingest(IngestDay("2026-07-22", [_ing_item("arxiv:1", "2026-07-22")]))

    assert store.list_ingest_dates() == ["2026-07-22", "2026-07-23"]
    assert [it["paper"].id for it in store.all_items()] == ["arxiv:1", "arxiv:2"]


def test_seen_map_records_which_ingest_day_holds_each_identity(tmp_path):
    store = Store(tmp_path / "data")
    store.mark_seen(["arxiv:1", "doi:10.1/x"], "2026-07-22")

    assert store.seen_map() == {"arxiv:1": "2026-07-22", "doi:10.1/x": "2026-07-22"}
    assert store.locate("doi:10.1/x") == "2026-07-22"
    assert store.locate("arxiv:missing") is None


def test_seen_index_reads_the_legacy_list_format(tmp_path):
    """Pre-migration the index was a flat list; those keys are seen but unlocatable."""
    root = tmp_path / "data"
    root.mkdir(parents=True)
    (root / "seen-index.json").write_text(json.dumps(["arxiv:old"]), encoding="utf-8")
    store = Store(root)

    assert store.seen_identities() == {"arxiv:old"}
    assert store.locate("arxiv:old") is None


def test_ensure_seen_identities_preserves_dated_entries_instead_of_flattening(tmp_path):
    """ensure_seen_identities is a legacy migration that predates dated entries.
    If it ever runs after mark_seen() has recorded ingest dates, it must merge
    new aliases in rather than rebuilding the index as a flat list — otherwise
    every already-recorded ingest date is silently destroyed."""
    st = Store(tmp_path)
    st.mark_seen(["arxiv:1"], "2026-07-22")

    st.ensure_seen_identities()

    assert st.locate("arxiv:1") == "2026-07-22"
    assert _SEEN_IDENTITY_SCHEMA in st.seen_identities()
