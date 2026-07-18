"""Print the model ids opencode go exposes, to confirm config model ids."""
import requests
from gdr import config

resp = requests.get(f"{config.OPENCODE_BASE_URL}/models",
                    headers={"Authorization": f"Bearer {config.get_api_key()}"}, timeout=30)
resp.raise_for_status()
for m in resp.json().get("data", []):
    print(m.get("id"))
