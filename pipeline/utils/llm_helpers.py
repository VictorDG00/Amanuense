from __future__ import annotations
import json
import time
from typing import Any
from .claude_client import LLMClient


def parse_json_response(raw: str, client: LLMClient | None = None, context: str = "") -> Any:
    text = raw.strip()
    # strip markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]  # drop opening fence
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # try to extract first JSON array or object
    for start_char, end_char in [("[", "]"), ("{", "}")]:
        start = text.find(start_char)
        end = text.rfind(end_char)
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass

    # correction prompt fallback
    if client is not None:
        correction_user = (
            f"The following text should be valid JSON but has syntax errors. "
            f"Return only the corrected JSON, nothing else:\n\n{raw[:4000]}"
        )
        corrected = client.call(
            system="You are a JSON repair assistant. Return only valid JSON, no explanations.",
            user=correction_user,
        )
        try:
            return json.loads(corrected.strip())
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse JSON from LLM response{f' ({context})' if context else ''}")


def batch_call(
    items: list[str],
    system: str,
    user_template: str,
    client: LLMClient | None = None,
    batch_size: int = 10,
    max_retries: int = 3,
) -> list[str]:
    if client is None:
        client = LLMClient()

    results: list[str] = []
    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        user = user_template.replace("{{ITEMS}}", "\n".join(batch))
        last_err: Exception | None = None
        for attempt in range(max_retries):
            try:
                result = client.call(system=system, user=user)
                results.append(result)
                break
            except Exception as e:
                last_err = e
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
        else:
            raise RuntimeError(f"batch_call failed for batch {i}: {last_err}")
    return results
