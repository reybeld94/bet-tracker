from __future__ import annotations

import unittest

import requests
from types import SimpleNamespace
from unittest.mock import patch

from app.ai.openai_client import (
    OPENAI_OUTPUT_TOKEN_BUDGETS,
    OpenAIClientError,
    _build_response_payload,
    request_pick,
)


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict, text: str | None = None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else str(payload)

    def json(self):
        return self._payload


class OpenAIClientTests(unittest.TestCase):
    def test_build_response_payload_uses_input_text_blocks(self) -> None:
        body = _build_response_payload("gpt-5", "high", {"a": 1})
        developer_content = body["input"][0]["content"][0]
        user_content = body["input"][1]["content"][0]

        self.assertEqual("input_text", developer_content["type"])
        self.assertEqual("input_text", user_content["type"])

    def test_request_pick_reports_reason_when_output_text_missing(self) -> None:
        settings = SimpleNamespace(
            openai_api_key_enc="key",
            openai_model="gpt-5",
            openai_reasoning_effort="high",
        )
        response_payload = {
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "output": [{"content": [{"type": "summary_text", "text": "partial response"}]}],
        }

        with patch("app.ai.openai_client.requests.post", return_value=_FakeResponse(200, response_payload)):
            with self.assertRaises(OpenAIClientError) as ctx:
                request_pick({"league": "NBA"}, settings)

        msg = str(ctx.exception)
        self.assertIn("missing output_text", msg)
        self.assertIn("status=incomplete", msg)
        self.assertIn("incomplete_reason=max_output_tokens", msg)


    def test_request_pick_retries_with_higher_max_output_tokens_on_incomplete(self) -> None:
        settings = SimpleNamespace(
            openai_api_key_enc="key",
            openai_model="gpt-5",
            openai_reasoning_effort="high",
        )
        incomplete_payload = {
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "output": [{"content": [{"type": "summary_text", "text": "partial"}]}],
        }
        success_payload = {"output_text": "{\"pick\":\"A\"}"}

        with patch(
            "app.ai.openai_client.requests.post",
            side_effect=[
                _FakeResponse(200, incomplete_payload),
                _FakeResponse(200, success_payload),
            ],
        ) as mock_post:
            parsed, _raw = request_pick({"league": "NBA"}, settings)

        self.assertEqual({"pick": "A"}, parsed)
        self.assertEqual(2, mock_post.call_count)
        first_body = mock_post.call_args_list[0].kwargs["json"]
        second_body = mock_post.call_args_list[1].kwargs["json"]
        self.assertEqual(900, first_body["max_output_tokens"])
        self.assertEqual(1800, second_body["max_output_tokens"])

    def test_request_pick_retries_on_timeout_then_succeeds(self) -> None:
        settings = SimpleNamespace(
            openai_api_key_enc="key",
            openai_model="gpt-5",
            openai_reasoning_effort="high",
        )
        response_payload = {"output_text": "{\"pick\":\"A\"}"}

        with patch(
            "app.ai.openai_client.requests.post",
            side_effect=[
                requests.Timeout("first timeout"),
                _FakeResponse(200, response_payload),
            ],
        ) as mock_post, patch("app.ai.openai_client.time.sleep") as mock_sleep:
            parsed, _raw = request_pick({"league": "NBA"}, settings)

        self.assertEqual({"pick": "A"}, parsed)
        self.assertEqual(2, mock_post.call_count)
        self.assertEqual((1,), mock_sleep.call_args.args)

    def test_request_pick_timeout_after_max_attempts(self) -> None:
        settings = SimpleNamespace(
            openai_api_key_enc="key",
            openai_model="gpt-5",
            openai_reasoning_effort="high",
        )

        with patch(
            "app.ai.openai_client.requests.post",
            side_effect=requests.Timeout("read timeout"),
        ) as mock_post, patch("app.ai.openai_client.time.sleep") as mock_sleep:
            with self.assertRaises(OpenAIClientError) as ctx:
                request_pick({"league": "NBA"}, settings)

        self.assertIn("failed after retries due to timeout", str(ctx.exception))
        self.assertEqual(18, mock_post.call_count)
        self.assertEqual(12, mock_sleep.call_count)


if __name__ == "__main__":
    unittest.main()
