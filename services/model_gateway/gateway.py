"""Provider-independent model gateway.

Agents talk to `ModelGateway.complete(...)`; adapters translate to each provider's HTTP API.
Only the final text answer is returned to callers — no hidden reasoning is requested, stored or shown.
Costs computed here are ESTIMATES from the price table below (override with AICIV_PRICE_<PROVIDER>_IN/OUT,
USD per million tokens). They are stored as estimated_cost_usd and never presented as a confirmed charge.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from services.core.config import get_settings


class ProviderError(Exception):
    """Normalized provider failure. kind ∈ auth | rate_limit | timeout | server | bad_request | unavailable."""

    def __init__(self, kind: str, message: str, provider: str) -> None:
        super().__init__(f"[{provider}:{kind}] {message}")
        self.kind = kind
        self.provider = provider

    @property
    def retryable(self) -> bool:
        return self.kind in {"rate_limit", "timeout", "server"}


@dataclass
class ModelRequest:
    system: str
    prompt: str
    max_tokens: int = 1500
    temperature: float = 0.0
    model: str | None = None  # per-agent model routing; None = the adapter's default


@dataclass
class ModelResponse:
    text: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    latency_ms: int
    raw_stop_reason: str | None = None
    capabilities: dict = field(default_factory=dict)


DEFAULT_PRICES = {  # USD per 1M tokens — placeholders, override via env; always labeled "estimated"
    "anthropic": (3.0, 15.0),
    "openai": (0.4, 1.6),
}
# Per-model-family placeholders (Opus for management, Haiku for research). Override with AICIV_PRICE_<FAMILY>_IN/OUT.
FAMILY_PRICES = {"opus": (15.0, 75.0), "sonnet": (3.0, 15.0), "haiku": (1.0, 5.0)}

# Rough char budget so a prompt never exceeds a conservative context window (~4 chars/token).
MAX_PROMPT_CHARS = 120_000


def estimate_cost(provider: str, input_tokens: int, output_tokens: int, model: str | None = None) -> float:
    pin, pout = DEFAULT_PRICES.get(provider, (0.0, 0.0))
    pin = float(os.environ.get(f"AICIV_PRICE_{provider.upper()}_IN", pin))
    pout = float(os.environ.get(f"AICIV_PRICE_{provider.upper()}_OUT", pout))
    family = next((f for f in FAMILY_PRICES if model and f in model), None)
    if family:
        pin = float(os.environ.get(f"AICIV_PRICE_{family.upper()}_IN", FAMILY_PRICES[family][0]))
        pout = float(os.environ.get(f"AICIV_PRICE_{family.upper()}_OUT", FAMILY_PRICES[family][1]))
    return round(input_tokens / 1e6 * pin + output_tokens / 1e6 * pout, 6)


def fit_context(text: str, limit: int = MAX_PROMPT_CHARS) -> str:
    if len(text) <= limit:
        return text
    head = limit * 2 // 3
    tail = limit - head - 64
    return text[:head] + "\n\n[... truncated for context window ...]\n\n" + text[-tail:]


def _classify(status: int) -> str:
    if status in (401, 403):
        return "auth"
    if status == 429:
        return "rate_limit"
    if status >= 500:
        return "server"
    return "bad_request"


class Adapter(Protocol):
    provider: str
    model: str
    capabilities: dict

    def complete(self, req: ModelRequest, timeout: float) -> ModelResponse: ...


class AnthropicAdapter:
    provider = "anthropic"
    capabilities = {"system_prompt": True, "tool_use": True, "json_mode": False}

    def __init__(self, api_key: str, model: str, client: httpx.Client | None = None) -> None:
        self.api_key = api_key
        self.model = model
        # AICIV_ANTHROPIC_BASE_URL: only for an API-compatible gateway you operate; defaults to Anthropic.
        self.client = client or httpx.Client(base_url=os.environ.get("AICIV_ANTHROPIC_BASE_URL", "https://api.anthropic.com"))

    def complete(self, req: ModelRequest, timeout: float) -> ModelResponse:
        started = time.monotonic()
        try:
            r = self.client.post(
                "/v1/messages",
                headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={
                    "model": req.model or self.model,
                    "max_tokens": req.max_tokens,
                    "temperature": req.temperature,
                    "system": req.system,
                    "messages": [{"role": "user", "content": fit_context(req.prompt)}],
                },
                timeout=timeout,
            )
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", str(exc), self.provider) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("unavailable", str(exc), self.provider) from exc
        if r.status_code >= 400:
            raise ProviderError(_classify(r.status_code), r.text[:300], self.provider)
        body = r.json()
        text = "".join(block.get("text", "") for block in body.get("content", []) if block.get("type") == "text")
        usage = body.get("usage", {})
        it, ot = int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
        return ModelResponse(text, self.provider, req.model or self.model, it, ot, estimate_cost(self.provider, it, ot, req.model or self.model),
                             int((time.monotonic() - started) * 1000), body.get("stop_reason"), self.capabilities)


class OpenAIAdapter:
    provider = "openai"
    capabilities = {"system_prompt": True, "tool_use": True, "json_mode": True}

    def __init__(self, api_key: str, model: str, client: httpx.Client | None = None) -> None:
        self.api_key = api_key
        self.model = model
        self.client = client or httpx.Client(base_url="https://api.openai.com")

    def complete(self, req: ModelRequest, timeout: float) -> ModelResponse:
        started = time.monotonic()
        try:
            r = self.client.post(
                "/v1/chat/completions",
                headers={"authorization": f"Bearer {self.api_key}"},
                json={
                    "model": req.model or self.model,
                    "max_tokens": req.max_tokens,
                    "temperature": req.temperature,
                    "messages": [{"role": "system", "content": req.system}, {"role": "user", "content": fit_context(req.prompt)}],
                },
                timeout=timeout,
            )
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", str(exc), self.provider) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("unavailable", str(exc), self.provider) from exc
        if r.status_code >= 400:
            raise ProviderError(_classify(r.status_code), r.text[:300], self.provider)
        body = r.json()
        choice = (body.get("choices") or [{}])[0]
        usage = body.get("usage", {})
        it, ot = int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
        return ModelResponse((choice.get("message") or {}).get("content") or "", self.provider, req.model or self.model, it, ot,
                             estimate_cost(self.provider, it, ot, req.model or self.model), int((time.monotonic() - started) * 1000),
                             choice.get("finish_reason"), self.capabilities)


class ModelGateway:
    """Routes an agent's request to its configured provider, falling back to whichever key exists."""

    def __init__(self, adapters: dict[str, Adapter] | None = None, max_retries: int = 2, timeout: float = 60.0) -> None:
        s = get_settings()
        if adapters is None:
            adapters = {}
            if s.anthropic_api_key:
                adapters["anthropic"] = AnthropicAdapter(s.anthropic_api_key, s.anthropic_model)
            if s.openai_api_key:
                adapters["openai"] = OpenAIAdapter(s.openai_api_key, s.openai_model)
            from services.model_gateway import plans
            if plans.enabled():
                # your Codex / Claude subscriptions take every call; API keys (if any) are not used as a fallback
                adapters = {"plan": plans.PlanAdapter()}
        self.adapters = adapters
        self.max_retries = max_retries
        self.timeout = timeout
        self._cache: dict = {}  # identical deterministic (temperature 0) requests are answered once

    @property
    def available(self) -> bool:
        return bool(self.adapters)

    def route(self, preferred_provider: str) -> Adapter:
        if "plan" in self.adapters:
            return self.adapters["plan"]
        if preferred_provider in self.adapters:
            return self.adapters[preferred_provider]
        if self.adapters:
            return next(iter(self.adapters.values()))
        raise ProviderError("unavailable", "no provider credentials configured", preferred_provider)

    def complete(self, req: ModelRequest, preferred_provider: str = "anthropic") -> ModelResponse:
        adapter = self.route(preferred_provider)
        if adapter.provider not in (preferred_provider, "plan"):
            req = ModelRequest(req.system, req.prompt, req.max_tokens, req.temperature, None)  # other provider: its own default model
        key = (adapter.provider, req.model, req.system, req.prompt, req.max_tokens) if req.temperature == 0 else None
        if key and key in self._cache:
            hit = self._cache[key]
            return ModelResponse(hit.text, hit.provider, hit.model, 0, 0, 0.0, 0, hit.raw_stop_reason, {**hit.capabilities, "cached": True})
        res = self._complete(adapter, req)
        if key:
            if len(self._cache) > 256:
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = res
        return res

    def _complete(self, adapter, req: ModelRequest) -> ModelResponse:
        attempt = 0
        while True:
            try:
                return adapter.complete(req, self.timeout)
            except ProviderError as exc:
                if not exc.retryable or attempt >= self.max_retries:
                    raise
                time.sleep(min(8.0, 0.5 * (2 ** attempt)))
                attempt += 1
