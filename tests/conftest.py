import pytest


class FakeLLM:
    """Test double for gdr.llm.LLM. Returns queued or keyed responses."""

    def __init__(self, responses):
        self._responses = responses
        self._i = 0
        self.calls = []

    def complete(self, model, system, user, temperature=0.3):
        self.calls.append({"model": model, "system": system, "user": user})
        if isinstance(self._responses, dict):
            for key, val in self._responses.items():
                if key in user:
                    return val(user) if callable(val) else val
            raise AssertionError(f"no keyed FakeLLM response matched user prompt")
        resp = self._responses[self._i]
        self._i += 1
        return resp


@pytest.fixture
def fake_llm_factory():
    return lambda responses: FakeLLM(responses)
