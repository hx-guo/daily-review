from gdr.llm import tier_model
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
