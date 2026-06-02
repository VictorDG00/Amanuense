from __future__ import annotations
import os
import time
from anthropic import Anthropic


class ClaudeClient:
    def __init__(self) -> None:
        self.client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
        self.model = os.environ.get("AMANUENSE_MODEL", "claude-sonnet-4-6")
        self.max_tokens = int(os.environ.get("AMANUENSE_MAX_TOKENS", "8192"))
        self._total_input_tokens = 0
        self._total_output_tokens = 0

    @property
    def total_cost_usd(self) -> float:
        input_cost = self._total_input_tokens * 3.0 / 1_000_000
        output_cost = self._total_output_tokens * 15.0 / 1_000_000
        return input_cost + output_cost

    def call(self, system: str, user: str, max_retries: int = 3) -> str:
        last_error: Exception | None = None
        for attempt in range(max_retries):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                self._total_input_tokens += response.usage.input_tokens
                self._total_output_tokens += response.usage.output_tokens
                return response.content[0].text
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
        raise RuntimeError(f"Claude call failed after {max_retries} attempts") from last_error
