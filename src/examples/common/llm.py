"""
Model gateway shared by the example workflows.

EXAMPLES_LLM_MODE selects where completions come from:
  offline (default)  each call returns the `offline_output` its caller supplies — what the
                     model is expected to answer — so the workflows run deterministically in
                     local runs, CI and Auto-Fix verification sandboxes (which have no network).
  live               the call goes to the Mistral API with MISTRAL_API_KEY.

Both modes apply the same request limits as the API: a prompt larger than the model's
context window is rejected, and an answer longer than `max_tokens` is cut off with
finish_reason="length".
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional

CONTEXT_WINDOWS: Dict[str, int] = {
    "mistral-small-latest": 131072,
    "mistral-medium-latest": 131072,
    "mistral-large-latest": 131072,
}

_CHARS_PER_TOKEN = 4


class ContextLengthExceededError(Exception):
    """The prompt does not fit in the model's context window (the API answers HTTP 400)."""


@dataclass
class LLMResult:
    content: str
    finish_reason: str
    prompt_tokens: int


def estimate_tokens(text: str) -> int:
    return len(text) // _CHARS_PER_TOKEN + 1


def _prompt_tokens(messages: List[Dict[str, str]]) -> int:
    return sum(estimate_tokens(m.get("content", "")) for m in messages)


async def complete(
    model: str,
    messages: List[Dict[str, str]],
    *,
    offline_output: str,
    max_tokens: Optional[int] = None,
    json_mode: bool = False,
) -> LLMResult:
    prompt_tokens = _prompt_tokens(messages)
    window = CONTEXT_WINDOWS.get(model, 131072)
    if prompt_tokens > window:
        raise ContextLengthExceededError(
            f"Prompt of {prompt_tokens} tokens exceeds the {window} token context window of {model}."
        )

    if os.getenv("EXAMPLES_LLM_MODE", "offline").lower() == "live":
        from mistralai import Mistral

        client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
        response = await client.chat.complete_async(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            response_format={"type": "json_object"} if json_mode else None,
        )
        choice = response.choices[0]
        return LLMResult(choice.message.content or "", choice.finish_reason or "stop", prompt_tokens)

    content, finish_reason = offline_output, "stop"
    if max_tokens is not None and estimate_tokens(content) > max_tokens:
        content, finish_reason = content[: max_tokens * _CHARS_PER_TOKEN], "length"
    return LLMResult(content, finish_reason, prompt_tokens)


def as_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False)
