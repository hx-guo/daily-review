from gdr.llm import make_llm, tier_model
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


def test_opencode_client_carries_a_session_header():
    # opencode requires x-opencode-session to optimise routing; from 2026-09-06
    # requests without it may be rejected outright.
    llm = make_llm(api_key="k", provider="opencode")

    assert llm._client.default_headers.get("x-opencode-session")


def test_an_explicit_session_id_is_used_verbatim():
    llm = make_llm(api_key="k", provider="opencode",
                   session_id="daily-review-2026-09-05")

    assert llm._client.default_headers["x-opencode-session"] == "daily-review-2026-09-05"


def test_hepai_client_sends_no_opencode_header():
    # x-opencode-session is meaningless to any other host; sending a vendor
    # header to HEPAI is at best noise and at worst a rejected request.
    llm = make_llm(api_key="k", provider="hepai")

    assert "x-opencode-session" not in llm._client.default_headers
    assert str(llm._client.base_url).startswith("https://aiapi.ihep.ac.cn/apiv2")


def test_make_llm_defaults_to_the_configured_provider():
    llm = make_llm(api_key="k")

    assert str(llm._client.base_url).startswith("https://aiapi.ihep.ac.cn/apiv2")
