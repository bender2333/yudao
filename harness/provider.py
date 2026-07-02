"""Provider config loader for the OpenAI-compatible gateway.

provider.md format (per spec §1):

    key: sk-xxxxx
    url: https://penguinapi.vip/
    gemini-2.5-flash

Rules: strip each line; ``key:`` prefix -> key; ``url:`` prefix -> url;
``model:`` prefix or a bare non-empty line -> model.
base_url = url.rstrip("/") + "/v1".

The key must never be logged or written anywhere.
"""

from __future__ import annotations

from openai import OpenAI


def load_provider(path: str = "provider.md") -> dict:
    """Parse provider.md into {"key", "url", "model"}.

    Raises ValueError if key or url is missing.
    """
    key = ""
    url = ""
    model = ""
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("key:"):
                key = line[len("key:"):].strip()
            elif line.startswith("url:"):
                url = line[len("url:"):].strip()
            elif line.startswith("model:"):
                model = line[len("model:"):].strip()
            else:
                # bare non-empty line -> model
                model = line
    if not key:
        raise ValueError("provider.md: missing 'key:'")
    if not url:
        raise ValueError("provider.md: missing 'url:'")
    return {"key": key, "url": url, "model": model}


def make_client(cfg: dict) -> OpenAI:
    """Build an OpenAI client pointed at the gateway.

    base_url = url + /v1, timeout=300, max_retries=0 (we retry ourselves).
    """
    base_url = cfg["url"].rstrip("/") + "/v1"
    return OpenAI(
        base_url=base_url,
        api_key=cfg["key"],
        timeout=300,
        max_retries=0,
    )
