"""Single entry point for every LLM call (Gemini on Vertex AI via ADC).

    LLM_MODE=live (default)  google-genai with vertexai=True; needs ADC + GOOGLE_CLOUD_PROJECT
    LLM_MODE=mock            no network; returns schema-valid stub data so code runs anywhere

Models: GEMINI_FAST_MODEL (default gemini-2.5-flash), GEMINI_SMART_MODEL (default gemini-2.5-pro).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import types
import typing
from typing import Any, Literal, TypeVar, get_args, get_origin

from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)
Tier = Literal["fast", "smart"]

_client = None


class LLMError(Exception):
    pass


def mode() -> str:
    return os.getenv("LLM_MODE", "live").lower()


def is_mock() -> bool:
    return mode() == "mock"


def _model(tier: Tier) -> str:
    if tier == "smart":
        return os.getenv("GEMINI_SMART_MODEL", "gemini-2.5-pro")
    return os.getenv("GEMINI_FAST_MODEL", "gemini-2.5-flash")


def _get_client():
    global _client
    if _client is None:
        from google import genai  # imported lazily so mock mode needs no SDK

        _client = genai.Client(
            vertexai=True,
            project=os.getenv("GOOGLE_CLOUD_PROJECT"),
            location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
        )
    return _client


def _thinking_budget(tier: Tier) -> int | None:
    """Flash thinks by default, which made outreach drafts take ~20s. Off for the fast tier unless overridden."""
    v = os.getenv("GEMINI_FAST_THINKING_BUDGET", "0") if tier == "fast" else os.getenv("GEMINI_SMART_THINKING_BUDGET")
    return int(v) if v not in (None, "") else None


async def _call(prompt: str, tier: Tier, config: dict[str, Any], retries: int = 2) -> str:
    client = _get_client()
    budget = _thinking_budget(tier)
    if budget is not None and "thinking_config" not in config:
        config = {**config, "thinking_config": {"thinking_budget": budget}}
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = await asyncio.wait_for(
                client.aio.models.generate_content(model=_model(tier), contents=prompt, config=config),
                timeout=float(os.getenv("LLM_TIMEOUT", "45")),
            )
            return resp.text or ""
        except Exception as e:  # SDK raises several types; retry them all
            last = e
            log.warning("LLM call failed (attempt %d): %s", attempt + 1, e)
            await asyncio.sleep(1.5 * (attempt + 1))
    raise LLMError(f"LLM call failed after retries: {last}")


def _extract_json(text: str) -> Any:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
        if start < 0:
            raise
        return json.loads(text[start : max(text.rfind("}"), text.rfind("]")) + 1])


async def generate_json(prompt: str, schema: type[T], tier: Tier = "fast", temperature: float = 0.2) -> T:
    """Return an instance of `schema`. Raises LLMError if the model can't produce valid JSON."""
    if is_mock():
        return mock_instance(schema)
    config = {
        "response_mime_type": "application/json",
        "response_schema": schema,
        "temperature": temperature,
    }
    text = await _call(prompt, tier, config)
    try:
        return schema.model_validate(_extract_json(text))
    except (ValidationError, json.JSONDecodeError, ValueError) as e:
        # one repair attempt without the response_schema constraint
        log.warning("LLM JSON invalid, retrying: %s", e)
        repair = (
            f"{prompt}\n\nReturn ONLY valid JSON matching this JSON schema, no prose:\n"
            f"{json.dumps(schema.model_json_schema())}"
        )
        text = await _call(repair, tier, {"response_mime_type": "application/json", "temperature": 0})
        try:
            return schema.model_validate(_extract_json(text))
        except Exception as e2:
            raise LLMError(f"Could not parse {schema.__name__} from LLM output: {e2}") from e2


async def generate_text(prompt: str, tier: Tier = "fast") -> str:
    if is_mock():
        return "[mock LLM text] " + prompt.strip().splitlines()[0][:120] if prompt.strip() else "[mock LLM text]"
    return (await _call(prompt, tier, {"temperature": 0.6})).strip()


# ---- mock data --------------------------------------------------------------


def _mock_value(annotation: Any, name: str) -> Any:
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin in (typing.Union, types.UnionType):
        non_none = [a for a in args if a is not type(None)]
        return _mock_value(non_none[0], name) if non_none else None
    if origin is Literal:
        return args[0]
    if origin in (list, tuple, set):
        inner = args[0] if args else str
        return [_mock_value(inner, name)]
    if origin is dict:
        return {}
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return mock_instance(annotation).model_dump()
    if annotation is int:
        return 50
    if annotation is float:
        return 0.5
    if annotation is bool:
        return False
    return f"mock {name}"


def mock_instance(schema: type[T]) -> T:
    data = {name: _mock_value(f.annotation, name) for name, f in schema.model_fields.items()}
    return schema.model_validate(data)
