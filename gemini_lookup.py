from __future__ import annotations

import json

from google import genai
from google.genai import errors, types

from ai_common import (
    CONFIDENCE_LEVELS,
    DATA_TYPES,
    MAX_SUGGESTIONS,
    QUANTITY_KINDS,
    research_prompt as _research_prompt,
    validate_suggestions_payload as _validate_suggestions_payload,
)
from modbus_core import InspectorError

AI_MODEL = "gemini-flash-latest"
REQUEST_TIMEOUT_MS = 45_000

EXTRACTION_INSTRUCTION = (
    "Fasse deine bisherige Recherche jetzt ausschliesslich als JSON gemäss dem vorgegebenen Schema "
    "zusammen. Kein Fliesstext, nur die strukturierten Felder."
)


def _point_schema() -> types.Schema:
    return types.Schema(
        type=types.Type.OBJECT,
        properties={
            "name": types.Schema(type=types.Type.STRING),
            "quantity_kind": types.Schema(type=types.Type.STRING, enum=list(QUANTITY_KINDS)),
            "function": types.Schema(type=types.Type.INTEGER, nullable=True),
            "function_guess_note": types.Schema(type=types.Type.STRING),
            "address": types.Schema(type=types.Type.INTEGER, nullable=True),
            "address_notes": types.Schema(type=types.Type.STRING),
            "data_type": types.Schema(type=types.Type.STRING, enum=list(DATA_TYPES)),
            "order": types.Schema(type=types.Type.STRING),
            "scale": types.Schema(type=types.Type.NUMBER, nullable=True),
            "unit": types.Schema(type=types.Type.STRING),
            "confidence": types.Schema(type=types.Type.STRING, enum=list(CONFIDENCE_LEVELS)),
            "source_url": types.Schema(type=types.Type.STRING),
            "source_note": types.Schema(type=types.Type.STRING),
            "caveats": types.Schema(type=types.Type.STRING),
        },
        required=["name", "quantity_kind", "data_type", "order", "confidence"],
    )


def _suggestions_schema() -> types.Schema:
    return types.Schema(
        type=types.Type.OBJECT,
        properties={
            "device_identified": types.Schema(type=types.Type.BOOLEAN),
            "general_notes": types.Schema(type=types.Type.STRING),
            "warnings": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)),
            "points": types.Schema(type=types.Type.ARRAY, items=_point_schema(), max_items=MAX_SUGGESTIONS),
        },
        required=["device_identified", "general_notes", "warnings", "points"],
    )


def _map_sdk_error(error: Exception) -> InspectorError:
    if isinstance(error, errors.APIError):
        if error.code in (401, 403):
            return InspectorError("Google-Gemini-API-Schlüssel ist ungültig.", 502)
        if error.code == 429:
            return InspectorError("Gemini-API: Rate-Limit erreicht, bitte später erneut versuchen.", 503)
        return InspectorError(f"Gemini-API-Fehler: {error.message}", 502)
    return InspectorError(f"Unerwarteter Fehler bei der Online-Suche: {error}", 502)


def _run_lookup(manufacturer: str, model: str, firmware: str, quantity: str | None, api_key: str) -> dict:
    client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS))
    prompt = _research_prompt(manufacturer, model, firmware, quantity)
    grounding_tool = types.Tool(google_search=types.GoogleSearch())
    try:
        research_response = client.models.generate_content(
            model=AI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(tools=[grounding_tool]),
        )
        contents = [
            types.Content(role="user", parts=[types.Part(text=prompt)]),
            types.Content(role="model", parts=[types.Part(text=research_response.text or "")]),
            types.Content(role="user", parts=[types.Part(text=EXTRACTION_INSTRUCTION)]),
        ]
        extraction_response = client.models.generate_content(
            model=AI_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_suggestions_schema(),
            ),
        )
    except errors.APIError as error:
        raise _map_sdk_error(error) from error
    except Exception as error:  # pragma: no cover - defensive catch-all
        raise _map_sdk_error(error) from error

    try:
        raw = json.loads(extraction_response.text)
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
