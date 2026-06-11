from __future__ import annotations
import os
import time
from openai import OpenAI

DEEPSEEK_BASE_URL = "https://api.deepseek.com"

# Preços DeepSeek-V3 (deepseek-chat) em USD/M tokens
_PRICE_INPUT_CACHE_MISS = 0.27 / 1_000_000
_PRICE_INPUT_CACHE_HIT = 0.07 / 1_000_000
_PRICE_OUTPUT = 1.10 / 1_000_000


class LLMClient:
    def __init__(self, use_cache: bool = True) -> None:
        self.client = OpenAI(
            api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
            base_url=DEEPSEEK_BASE_URL,
        )
        self.model = os.environ.get("AMANUENSE_MODEL", "deepseek-chat")
        self.max_tokens = int(os.environ.get("AMANUENSE_MAX_TOKENS", "8192"))
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._total_cached_tokens = 0
        self._cache_hits = 0

        self._cache = None
        cache_enabled = use_cache and os.environ.get("AMANUENSE_LLM_CACHE", "1") != "0"
        if cache_enabled:
            from .llm_cache import LLMCache
            ttl_days = int(os.environ.get("AMANUENSE_CACHE_TTL_DAYS", "30"))
            self._cache = LLMCache(ttl_days=ttl_days)

    @property
    def total_cost_usd(self) -> float:
        uncached = self._total_input_tokens - self._total_cached_tokens
        return (
            uncached * _PRICE_INPUT_CACHE_MISS
            + self._total_cached_tokens * _PRICE_INPUT_CACHE_HIT
            + self._total_output_tokens * _PRICE_OUTPUT
        )

    def call(self, system: str, user: str, max_retries: int = 3) -> str:
        if self._cache is not None:
            cached = self._cache.get(system, user)
            if cached is not None:
                self._cache_hits += 1
                return cached

        last_error: Exception | None = None
        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                )
                usage = response.usage
                if usage:
                    self._total_input_tokens += usage.prompt_tokens
                    self._total_output_tokens += usage.completion_tokens
                    # DeepSeek reporta cache hits em prompt_cache_hit_tokens
                    cached_tokens = getattr(usage, "prompt_cache_hit_tokens", 0) or 0
                    self._total_cached_tokens += cached_tokens
                result = response.choices[0].message.content or ""
                if self._cache is not None:
                    self._cache.set(system, user, result)
                return result
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
        raise RuntimeError(f"LLM call failed after {max_retries} attempts") from last_error


# Alias para não quebrar imports existentes
ClaudeClient = LLMClient
