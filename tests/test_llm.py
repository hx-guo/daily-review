from gdr.llm import OpenCodeLLM, tier_model
from gdr import config


def test_tier_model_maps_to_config():
    assert tier_model("triage") == config.MODEL_TRIAGE
    assert tier_model("write") == config.MODEL_WRITE
    assert tier_model("synth") == config.MODEL_SYNTH


def test_fake_llm_records_and_replies(fake_llm_factory):
    llm = fake_llm_factory(["hello"])
    out = llm.complete(model="m", system="s", user="u")
    assert out == "hello"
    assert llm.calls[0]["model"] == "m"
    assert llm.calls[0]["user"] == "u"


def test_client_carries_an_opencode_session_header():
    # opencode requires x-opencode-session to optimise routing; from 2026-09-06
    # requests without it may be rejected outright.
    llm = OpenCodeLLM(api_key="k")

    assert llm._client.default_headers.get("x-opencode-session")


def test_an_explicit_session_id_is_used_verbatim():
    llm = OpenCodeLLM(api_key="k", session_id="daily-review-2026-09-05")

    assert llm._client.default_headers["x-opencode-session"] == "daily-review-2026-09-05"
