import uuid
from typing import Protocol

from gdr import config


class LLM(Protocol):
    def complete(self, model: str, system: str, user: str, temperature: float = 0.3) -> str:
        ...


_TIERS = {
    "triage": config.MODEL_TRIAGE,
    "write": config.MODEL_WRITE,
    "synth": config.MODEL_SYNTH,
}


def tier_model(tier: str) -> str:
    return _TIERS[tier]


class OpenAICompatLLM:
    """Chat completions against any OpenAI-compatible host."""

    def __init__(self, api_key: str, base_url: str, extra_headers: dict | None = None):
        from openai import OpenAI  # imported lazily so tests don't need the network
        self._client = OpenAI(api_key=api_key, base_url=base_url,
                              max_retries=config.OPENAI_MAX_RETRIES,
                              default_headers=extra_headers or {})

    def complete(self, model: str, system: str, user: str, temperature: float = 0.3) -> str:
        resp = self._client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
        )
        return resp.choices[0].message.content or ""


def make_llm(api_key: str = "", provider: str = "", session_id: str = "") -> OpenAICompatLLM:
    """The client for one backend, carrying only the headers that backend wants.

    `provider` is for tests and one-off scripts; production selects it through
    GDR_LLM_PROVIDER, which also decides which key variable get_api_key reads.
    """
    name = provider or config.LLM_PROVIDER
    settings = config.resolve_provider(name)
    headers = {}
    if settings.get("session_header"):
        # opencode uses x-opencode-session to group a caller's requests; from
        # 2026-09-06 it may reject requests that omit it. One id per instance
        # means one id per pipeline run, which is the grouping they want.
        headers[settings["session_header"]] = session_id or f"daily-review-{uuid.uuid4().hex}"
    # GDR_LLM_BASE_URL overrides only the provider actually selected by config.
    base_url = config.LLM_BASE_URL if name == config.LLM_PROVIDER else settings["base_url"]
    return OpenAICompatLLM(api_key or config.get_api_key(), base_url, headers)
