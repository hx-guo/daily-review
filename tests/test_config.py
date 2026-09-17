import os
import pytest
from gdr import config

def test_layer_for_thresholds():
    assert config.layer_for(85) == "core"
    assert config.layer_for(70) == "core"
    assert config.layer_for(55) == "related"
    assert config.layer_for(40) == "related"
    assert config.layer_for(20) == "edge"

def test_get_api_key_reads_the_selected_providers_variable(monkeypatch):
    monkeypatch.setenv("HEPAI_API_KEY", "sk-test")
    assert config.get_api_key() == "sk-test"

def test_get_api_key_missing_names_the_variable(monkeypatch):
    # The message has to name the variable the selected provider actually reads,
    # or a provider switch leaves you hunting for a key you did set.
    monkeypatch.delenv("HEPAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="HEPAI_API_KEY"):
        config.get_api_key()

def test_profile_and_categories_present():
    assert "GRB" in config.TEAM_PROFILE or "伽马暴" in config.TEAM_PROFILE
    assert "astro-ph.HE" in config.ARXIV_CATEGORIES

def test_sync_constants_present():
    assert config.FETCH_WINDOW_DAYS >= 1
    assert config.ARXIV_PAGE_SIZE >= 1
    assert config.ADS_PAGE_SIZE >= 1
    assert "property:refereed" in config.ADS_INGEST_QUERY
    assert "bibstem:" not in config.ADS_INGEST_QUERY  # never ingest whole journal issues
    assert config.MAX_CONCURRENCY >= 1

def test_resolve_provider_hepai_ids_are_namespaced():
    # HEPAI exposes every model under a vendor prefix; `glm-5.2` has no bare
    # alias there, so the whole tier set has to switch together with the host.
    p = config.resolve_provider("hepai")
    assert p["base_url"] == "https://aiapi.ihep.ac.cn/apiv2"
    assert p["key_env"] == "HEPAI_API_KEY"
    assert p["models"]["synth"] == "zhipu/glm-5.2"

def test_default_tier_models_come_from_the_provider():
    # HEPAI is the default backend; opencode stays selectable as a fallback.
    assert config.LLM_PROVIDER == "hepai"
    assert config.LLM_BASE_URL == "https://aiapi.ihep.ac.cn/apiv2"
    assert config.MODEL_TRIAGE == "deepseek-ai/deepseek-v4-flash"
    assert config.MODEL_WRITE == "deepseek-ai/deepseek-v4-pro"
    assert config.MODEL_SYNTH == "zhipu/glm-5.2"

def test_unknown_provider_names_the_known_ones():
    with pytest.raises(RuntimeError, match="hepai"):
        config.resolve_provider("nope")
