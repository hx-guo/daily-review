import os
import pytest
from gdr import config

def test_layer_for_thresholds():
    assert config.layer_for(85) == "core"
    assert config.layer_for(70) == "core"
    assert config.layer_for(55) == "related"
    assert config.layer_for(40) == "related"
    assert config.layer_for(20) == "edge"

def test_get_api_key_reads_env(monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-test")
    assert config.get_api_key() == "sk-test"

def test_get_api_key_missing_raises(monkeypatch):
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        config.get_api_key()

def test_profile_and_categories_present():
    assert "GRB" in config.TEAM_PROFILE or "伽马暴" in config.TEAM_PROFILE
    assert "astro-ph.HE" in config.ARXIV_CATEGORIES

def test_sync_constants_present():
    assert config.FETCH_WINDOW_DAYS >= 1
    assert config.ARXIV_PAGE_SIZE >= 1
    assert config.ADS_PAGE_SIZE >= 1
    assert "property:refereed" in config.ADS_INGEST_QUERY
    assert config.MAX_CONCURRENCY >= 1
