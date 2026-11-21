"""One async JSON function for both tiers: retry, fallback, cache (§7.1)."""
import asyncio
import hashlib
import json
import re
from typing import Literal, TypeVar

from openai import AsyncOpenAI, APIStatusError, APITimeoutError, APIConnectionError
from pydantic import BaseModel, ValidationError

from .config import (LOCAL_LLM_BASE_URL, LOCAL_LLM_MODEL, OPENROUTER_API_KEY, OPENROUTER_MODELS, LLM_CACHE,
                     CACHE_DIR, LOCAL_TIMEOUT, REMOTE_TIMEOUT)

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    pass


_local = AsyncOpenAI(base_url=LOCAL_LLM_BASE_URL, api_key="ollama", timeout=LOCAL_TIMEOUT, max_retries=0)
_remote = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY or "missing",
                      timeout=REMOTE_TIMEOUT, max_retries=0, default_headers={"X-Title": "Ingaze Engine"})


def _parse(text: str, schema: type[T]) -> T:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    text = re.sub(r"```(?:json)?", "", text)
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b < a:
        raise ValueError("no JSON object found")
    return schema.model_validate_json(text[a:b + 1])


async def llm_json(tier: Literal["local", "remote"], system: str, user: str, schema: type[T],
                   temperature: float = 0.2) -> tuple[T, dict]:
    models = [LOCAL_LLM_MODEL] if tier == "local" else OPENROUTER_MODELS
    client = _local if tier == "local" else _remote
    system = system + "\n\nReturn ONLY one JSON object matching this JSON Schema:\n" + json.dumps(schema.model_json_schema())
    errors = []
    for model in models:
        key = hashlib.sha256((model + system + user + schema.__name__).encode()).hexdigest()
        path = CACHE_DIR / f"{key}.json"
        if LLM_CACHE and path.exists():
            return schema.model_validate_json(path.read_text(encoding="utf-8")), {"model": model, "cached": True, "attempts": 0}
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        extra = {"response_format": {"type": "json_object"}} if tier == "local" else {}
        attempts, fix_tries, net_tries = 0, 0, 0
        while True:
            attempts += 1
            try:
                resp = await client.chat.completions.create(model=model, messages=messages, temperature=temperature, **extra)
                raw = resp.choices[0].message.content or ""
            except (APIStatusError, APITimeoutError, APIConnectionError) as e:
                status = getattr(e, "status_code", None)
                if (status is None or status == 429 or status >= 500) and net_tries < 1:
                    net_tries += 1
                    await asyncio.sleep(2 ** attempts)
                    continue
                errors.append(f"{model}: {e}")
                break
            try:
                obj = _parse(raw, schema)
            except (ValidationError, ValueError) as e:
                if fix_tries >= 2:
                    errors.append(f"{model}: invalid JSON after retries: {str(e)[:300]}")
                    break
                fix_tries += 1
                messages += [{"role": "assistant", "content": raw},
                             {"role": "user", "content": f"Your JSON was invalid: {str(e)[:1500]}. Return the corrected JSON only."}]
                continue
            CACHE_DIR.mkdir(exist_ok=True)
            path.write_text(obj.model_dump_json(), encoding="utf-8")
            return obj, {"model": model, "cached": False, "attempts": attempts}
    raise LLMError(f"all {tier} models failed: " + " | ".join(errors or ["no models configured"]))
