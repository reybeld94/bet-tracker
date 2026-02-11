from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.ai.openai_client import OpenAIClientError, _build_response_payload, request_pick


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
            "output": [
                {"content": [{"type": "summary_text", "text": "partial response"}]}
            ],
        }

        with patch("app.ai.openai_client.requests.post", return_value=_FakeResponse(200, response_payload)):
            with self.assertRaises(OpenAIClientError) as ctx:
                request_pick({"league": "NBA"}, settings)

        msg = str(ctx.exception)
        self.assertIn("missing output_text", msg)
        self.assertIn("status=incomplete", msg)
        self.assertIn("incomplete_reason=max_output_tokens", msg)


if __name__ == "__main__":
    unittest.main()
