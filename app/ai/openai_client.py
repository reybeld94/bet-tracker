from __future__ import annotations

import json
import time
from typing import Any

import requests

MAX_ERROR_SNIPPET = 2000
OPENAI_CONNECT_TIMEOUT_SECONDS = 15
OPENAI_READ_TIMEOUT_SECONDS = 150
OPENAI_MAX_ATTEMPTS = 3

from app.ai.prompt import DEV_PROMPT
from app.ai.schema import PICK_SCHEMA
from app.settings import decrypt_api_key


class OpenAIClientError(RuntimeError):
    pass


def _truncate(value: str, limit: int = MAX_ERROR_SNIPPET) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "...<truncated>"


def _response_debug_summary(response_json: dict[str, Any]) -> str:
    parts: list[str] = []

    status = response_json.get("status")
    if status:
        parts.append(f"status={status}")

    incomplete_details = response_json.get("incomplete_details")
    if isinstance(incomplete_details, dict) and incomplete_details:
        reason = incomplete_details.get("reason")
        if reason:
            parts.append(f"incomplete_reason={reason}")

    error = response_json.get("error")
    if isinstance(error, dict) and error:
        message = error.get("message")
        code = error.get("code")
        if message:
            parts.append(f"error_message={message}")
        if code:
            parts.append(f"error_code={code}")

    output = response_json.get("output")
    if isinstance(output, list):
        content_types: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            for content in item.get("content", []):
                if isinstance(content, dict) and content.get("type"):
                    content_types.append(str(content.get("type")))
        if content_types:
            parts.append(f"output_content_types={content_types}")

    if not parts:
        parts.append("no_debug_fields")

    parts.append("response_json=" + _truncate(json.dumps(response_json, ensure_ascii=False)))
    return "; ".join(parts)


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
        "tools": [{"type": "web_search_preview"}],
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
    response = None
    last_exception: requests.RequestException | None = None
    for attempt in range(1, OPENAI_MAX_ATTEMPTS + 1):
        try:
            response = requests.post(
                "https://api.openai.com/v1/responses",
                headers=headers,
                json=body,
                timeout=(OPENAI_CONNECT_TIMEOUT_SECONDS, OPENAI_READ_TIMEOUT_SECONDS),
            )
            break
        except requests.Timeout as exc:
            last_exception = exc
            if attempt == OPENAI_MAX_ATTEMPTS:
                break
            time.sleep(attempt)
        except requests.RequestException as exc:
            raise OpenAIClientError(f"OpenAI request failed: {exc}") from exc

    if response is None:
        assert last_exception is not None
        raise OpenAIClientError(
            "OpenAI request failed after retries due to timeout. "
            f"Try lowering reasoning effort or retrying later. Last error: {last_exception}"
        ) from last_exception

    raw_response_text = response.text
    try:
        response_json = response.json()
    except ValueError as exc:
        if response.status_code >= 400:
            raise OpenAIClientError(
                f"OpenAI API error {response.status_code}: non-JSON response={_truncate(raw_response_text)}"
            ) from exc
        raise OpenAIClientError(
            "OpenAI API returned non-JSON response: " + _truncate(raw_response_text)
        ) from exc

    if response.status_code >= 400:
        raise OpenAIClientError(
            f"OpenAI API error {response.status_code}: {_response_debug_summary(response_json)}"
        )
    output_text = _extract_output_text(response_json)
    if not output_text:
        raise OpenAIClientError(
            "OpenAI response missing output_text: " + _response_debug_summary(response_json)
        )
    try:
        parsed = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise OpenAIClientError(
            "OpenAI response was not valid JSON; output_text=" + _truncate(output_text)
        ) from exc
    return parsed, json.dumps(response_json, ensure_ascii=False)
