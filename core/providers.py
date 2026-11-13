"""Hosted AI provider (Anthropic Messages API) using only the standard library.

- The API key comes from the environment, never from code or logs.
- Prompt text and replies are never logged. Errors carry only a short, safe message.
- Cost is estimated from the token counts in the reply, in paise. The rates are
  settings you must fill from the provider's price page; the defaults are rough.
"""

import json
import os
import time
import urllib.error
import urllib.request

from .gateway import GatewayError, Provider, ProviderResult

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-5-5"
_RETRY_STATUS = (429, 500, 502, 503, 529)


class AnthropicProvider(Provider):
    def __init__(self, api_key, model=DEFAULT_MODEL, max_tokens=3000, timeout=60,
                 paise_per_mtok_in=30000, paise_per_mtok_out=150000, url=API_URL, sleep=time.sleep):
        if not api_key:
            raise GatewayError("no API key")
        self._api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.rate_in = paise_per_mtok_in
        self.rate_out = paise_per_mtok_out
        self.url = url
        self._sleep = sleep

    def __repr__(self):  # never show the key in logs or tracebacks
        return "AnthropicProvider(model=%r)" % self.model

    def _post(self, body):
        request = urllib.request.Request(
            self.url,
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={
                "content-type": "application/json",
                "x-api-key": self._api_key,
                "anthropic-version": API_VERSION,
            },
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read(4 * 1024 * 1024).decode("utf-8"))

    def complete(self, system, user):
        body = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        reply = None
        for attempt in range(2):
            try:
                reply = self._post(body)
                break
            except urllib.error.HTTPError as err:
                if err.code in _RETRY_STATUS and attempt == 0:
                    self._sleep(2)
                    continue
                if err.code in (401, 403):
                    raise GatewayError("the AI key was rejected (%d): check ANTHROPIC_API_KEY" % err.code)
                raise GatewayError("the AI service returned an error (%d)" % err.code)
            except (urllib.error.URLError, TimeoutError, OSError):
                if attempt == 0:
                    self._sleep(2)
                    continue
                raise GatewayError("could not reach the AI service")
            except ValueError:
                raise GatewayError("the AI service sent an unreadable reply")
        parts = reply.get("content") if isinstance(reply, dict) else None
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict) and p.get("type") == "text") if isinstance(parts, list) else ""
        if not text.strip():
            raise GatewayError("the AI service sent an empty reply")
        usage = reply.get("usage") or {}
        tokens_in = int(usage.get("input_tokens") or 0)
        tokens_out = int(usage.get("output_tokens") or 0)
        cost = -(-(tokens_in * self.rate_in + tokens_out * self.rate_out) // 1_000_000)  # round up
        return ProviderResult(text, cost)


def provider_from_env(environ=None):
    """The configured hosted provider, or None when no key is set."""
    env = os.environ if environ is None else environ
    key = (env.get("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        return None
    if not key.startswith("sk-ant-") or len(key) < 40:
        raise GatewayError("ANTHROPIC_API_KEY does not look like a real key (it starts with sk-ant- and is long)")
    return AnthropicProvider(
        key,
        model=env.get("AI_MODEL", DEFAULT_MODEL),
        paise_per_mtok_in=int(env.get("AI_PAISE_PER_MTOK_IN", 30000)),
        paise_per_mtok_out=int(env.get("AI_PAISE_PER_MTOK_OUT", 150000)),
    )
