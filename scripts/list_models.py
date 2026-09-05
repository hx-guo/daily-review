"""Print the model ids opencode go exposes, to confirm config model ids."""
import uuid

import requests
from gdr import config

resp = requests.get(f"{config.OPENCODE_BASE_URL}/models",
                    headers={"Authorization": f"Bearer {config.get_api_key()}",
                             # opencode may reject header-less requests from 2026-09-06;
                             # this is the tool used to diagnose that, so it needs one too.
                             "x-opencode-session": f"list-models-{uuid.uuid4().hex}"},
                    timeout=30)
resp.raise_for_status()
for m in resp.json().get("data", []):
    print(m.get("id"))
