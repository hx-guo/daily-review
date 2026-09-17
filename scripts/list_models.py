"""Print the model ids the selected provider exposes, to confirm config model ids."""
import uuid

import requests
from gdr import config

_provider = config.resolve_provider(config.LLM_PROVIDER)
headers = {"Authorization": f"Bearer {config.get_api_key()}"}
if _provider.get("session_header"):
    # opencode may reject header-less requests from 2026-09-06; this is the tool
    # used to diagnose that, so it needs one too.
    headers[_provider["session_header"]] = f"list-models-{uuid.uuid4().hex}"

resp = requests.get(f"{config.LLM_BASE_URL}/models", headers=headers, timeout=30)
resp.raise_for_status()
for m in resp.json().get("data", []):
    print(m.get("id"))
