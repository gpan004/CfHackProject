import asyncio
import contextvars
import hashlib
import json
import os

from openai import APIStatusError, APITimeoutError, APIConnectionError
from pydantic import ValidationError

from ..config import LOCAL_LLM_MODEL, OPENROUTER_MODELS, LLM_CACHE, CACHE_DIR
from ..llm import _local, _remote, _parse, LLMError

SEED = 7
CACHE_V2 = CACHE_DIR / "v2"
FRESH = contextvars.ContextVar("v2_fresh", default=False)   # set by the pipeline for --fresh runs


def tier_for(role_tier: str) -> str:
    return "remote" if role_tier == "local" and os.getenv("V2_LOCAL_TIER", "local") == "remote" else role_tier


async def call(role: str, tier: str, system: str, user: str, schema, fresh: bool = False):
    """Returns (parsed object, info). Tries the role's tier first, then the other tier (OpenRouter <-> local Mistral),
    so a quota or a GPU outage does not silently remove an agent. Raises LLMError only if every model fails."""
    tier = tier_for(tier)
    other = "local" if tier == "remote" else "remote"
    plan = [(m, _local if tier == "local" else _remote, tier) for m in ([LOCAL_LLM_MODEL] if tier == "local" else OPENROUTER_MODELS)]
    plan += [(m, _local if other == "local" else _remote, other) for m in ([LOCAL_LLM_MODEL] if other == "local" else OPENROUTER_MODELS)]
    system = system + "\n\nReturn ONLY one JSON object matching this JSON Schema:\n" + json.dumps(schema.model_json_schema())
    key = hashlib.sha256(("v2|" + role + "|" + system + "|" + user + "|" + schema.__name__).encode()).hexdigest()
    path = CACHE_V2 / f"{key}.json"
    if LLM_CACHE and not (fresh or FRESH.get()) and path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        return schema.model_validate(data["obj"]), {"model": data["model"], "cached": True, "attempts": 0}
    errors = []
    for model, client, t in plan:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        extra = {"response_format": {"type": "json_object"}} if t == "local" else {}
        attempts, fix_tries, net_tries = 0, 0, 0
        while True:
            attempts += 1
            try:
                resp = await client.chat.completions.create(model=model, messages=messages, temperature=0, seed=SEED, **extra)
                raw = resp.choices[0].message.content or ""
            except (APIStatusError, APITimeoutError, APIConnectionError) as e:
                status = getattr(e, "status_code", None)
                if "per-day" in str(e) or "credits" in str(e):      # daily quota: retrying cannot help
                    errors.append(f"{model}: daily quota reached")
                    break
                if (status is None or status == 429 or status >= 500) and net_tries < 2:
                    net_tries += 1
                    await asyncio.sleep(3 * net_tries)
                    continue
                errors.append(f"{model}: {str(e)[:200]}")
                break
            try:
                obj = _parse(raw, schema)
            except (ValidationError, ValueError) as e:
                if fix_tries >= 2:
                    errors.append(f"{model}: invalid JSON after retries: {str(e)[:200]}")
                    break
                fix_tries += 1
                messages += [{"role": "assistant", "content": raw},
                             {"role": "user", "content": f"Your JSON was invalid: {str(e)[:1200]}. Return the corrected JSON only."}]
                continue
            CACHE_V2.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"model": model, "role": role, "obj": obj.model_dump()}, ensure_ascii=False), encoding="utf-8")
            return obj, {"model": model, "cached": False, "attempts": attempts}
    raise LLMError(f"{role}: all models failed (OpenRouter and local): " + " | ".join(errors or ["no models configured"]))
