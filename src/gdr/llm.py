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


class OpenCodeLLM:
    def __init__(self, api_key: str, base_url: str = config.OPENCODE_BASE_URL):
        from openai import OpenAI  # imported lazily so tests don't need the network
        self._client = OpenAI(api_key=api_key, base_url=base_url)

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
