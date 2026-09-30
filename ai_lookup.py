from __future__ import annotations

import json

import anthropic

from ai_common import (
    CONFIDENCE_LEVELS,
    DATA_TYPES,
    MAX_SUGGESTIONS,
    QUANTITY_KINDS,
    research_prompt as _research_prompt,
    validate_suggestions_payload as _validate_suggestions_payload,
)
from modbus_core import InspectorError

AI_MODEL = "claude-sonnet-5"
REQUEST_TIMEOUT_SECONDS = 45.0

SUGGESTIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "device_identified": {"type": "boolean"},
        "general_notes": {"type": "string"},
        "warnings": {"type": "array", "items": {"type": "string"}},
        "points": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "quantity_kind": {"type": "string", "enum": list(QUANTITY_KINDS)},
                    "function": {"type": ["integer", "null"]},
                    "function_guess_note": {"type": "string"},
                    "address": {"type": ["integer", "null"]},
                    "address_notes": {"type": "string"},
                    "data_type": {"type": "string", "enum": list(DATA_TYPES)},
                    "order": {"type": "string"},
                    "scale": {"type": ["number", "null"]},
                    "unit": {"type": "string"},
                    "confidence": {"type": "string", "enum": list(CONFIDENCE_LEVELS)},
                    "source_url": {"type": "string"},
                    "source_note": {"type": "string"},
                    "caveats": {"type": "string"},
                },
                "required": ["name", "quantity_kind", "data_type", "order", "confidence"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["device_identified", "general_notes", "warnings", "points"],
    "additionalProperties": False,
}


def _web_search_tool() -> dict:
    return {"type": "web_search_20260209", "name": "web_search", "max_uses": 5}


def _map_sdk_error(error: Exception) -> InspectorError:
    if isinstance(error, anthropic.AuthenticationError):
        return InspectorError("Anthropic-API-Schlüssel ist ungültig.", 502)
    if isinstance(error, anthropic.PermissionDeniedError):
        return InspectorError("Anthropic-API-Schlüssel hat keine ausreichenden Berechtigungen.", 502)
    if isinstance(error, anthropic.RateLimitError):
        return InspectorError("Anthropic-API: Rate-Limit erreicht, bitte später erneut versuchen.", 503)
    if isinstance(error, anthropic.APIConnectionError):
        return InspectorError("Keine Verbindung zur Anthropic-API möglich.", 502)
    if isinstance(error, anthropic.APIStatusError):
        return InspectorError(f"Anthropic-API-Fehler: {error.message}", 502)
    return InspectorError(f"Unerwarteter Fehler bei der Online-Suche: {error}", 502)


def _run_lookup(manufacturer: str, model: str, firmware: str, quantity: str | None, api_key: str) -> dict:
    client = anthropic.Anthropic(api_key=api_key)
    prompt = _research_prompt(manufacturer, model, firmware, quantity)
    try:
        response = client.with_options(timeout=REQUEST_TIMEOUT_SECONDS).messages.create(
            model=AI_MODEL,
            max_tokens=4096,
            tools=[_web_search_tool()],
            output_config={"format": {"type": "json_schema", "schema": SUGGESTIONS_SCHEMA}},
            messages=[{"role": "user", "content": prompt}],
        )
    except (
        anthropic.AuthenticationError,
        anthropic.PermissionDeniedError,
        anthropic.RateLimitError,
        anthropic.APIConnectionError,
        anthropic.APIStatusError,
    ) as error:
        raise _map_sdk_error(error) from error
    except Exception as error:  # pragma: no cover - defensive catch-all
        raise _map_sdk_error(error) from error

    text_block = next((block for block in response.content if block.type == "text"), None)
    if text_block is None:
        raise InspectorError("Antwort der KI enthielt keinen auswertbaren Text.", 502)
    try:
        raw = json.loads(text_block.text)
    except (TypeError, ValueError) as error:
        raise InspectorError("Antwort der KI war kein gültiges JSON.", 502) from error

    return _validate_suggestions_payload(raw)


def lookup_device_points(manufacturer: str, model: str, firmware: str, api_key: str) -> dict:
    return _run_lookup(manufacturer, model, firmware, None, api_key)


def lookup_quantity(manufacturer: str, model: str, firmware: str, quantity: str, api_key: str) -> dict:
    cleaned_quantity = str(quantity or "").strip()[:160]
    if not cleaned_quantity:
        raise InspectorError("Bitte eine Grösse angeben, nach der gesucht werden soll.", 400)
    return _run_lookup(manufacturer, model, firmware, cleaned_quantity, api_key)
