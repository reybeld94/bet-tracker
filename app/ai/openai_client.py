from __future__ import annotations

import json
from typing import Any

import requests

from app.ai.prompt import DEV_PROMPT
from app.ai.schema import PICK_SCHEMA
from app.settings import decrypt_api_key


class OpenAIClientError(RuntimeError):
    pass


def _build_response_payload(model: str, reasoning_effort: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": model,
        "reasoning": {"effort": reasoning_effort},
        "input": [
            {
                "role": "developer",
                "content": [{"type": "input_text", "text": DEV_PROMPT}],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": json.dumps(payload, ensure_ascii=False),
                    }
                ],
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": PICK_SCHEMA["name"],
                "schema": PICK_SCHEMA["schema"],
            }
        },
    }


def _extract_output_text(response_json: dict[str, Any]) -> str:
    if "output_text" in response_json and response_json["output_text"]:
        return response_json["output_text"]
    output = response_json.get("output") or []
    for item in output:
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                return content.get("text", "")
    return ""


def request_pick(payload: dict[str, Any], settings) -> tuple[dict[str, Any], str]:
    api_key = decrypt_api_key(settings.openai_api_key_enc)
    if not api_key:
        raise OpenAIClientError("Missing OpenAI API key")

    body = _build_response_payload(
        settings.openai_model,
        settings.openai_reasoning_effort,
        payload,
    )
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers=headers,
        json=body,
        timeout=90,
    )
    if response.status_code >= 400:
        raise OpenAIClientError(
            f"OpenAI API error {response.status_code}: {response.text}"
        )
    response_json = response.json()
    output_text = _extract_output_text(response_json)
    if not output_text:
        raise OpenAIClientError("OpenAI response missing output_text")
    try:
        parsed = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise OpenAIClientError("OpenAI response was not valid JSON") from exc
    return parsed, json.dumps(response_json, ensure_ascii=False)
