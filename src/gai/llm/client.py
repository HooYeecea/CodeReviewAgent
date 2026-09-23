"""OpenAI-compatible Chat Completions client."""

from __future__ import annotations

from typing import Any

import httpx

from gai.config import Settings


class LLMError(RuntimeError):
    """Raised when the LLM API call fails."""


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def chat(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.2,
    ) -> str:
        if not self.settings.api_key:
            raise LLMError(
                "API key not configured. Set GAI_API_KEY / OPENAI_API_KEY "
                "or run: gai config --api-key <key>"
            )

        url = f"{self.settings.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }

        try:
            with httpx.Client(timeout=self.settings.timeout) as client:
                response = client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise LLMError(f"LLM request timed out after {self.settings.timeout}s") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM request failed: {exc}") from exc

        if response.status_code >= 400:
            detail = response.text[:500]
            raise LLMError(f"LLM API error {response.status_code}: {detail}")

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMError("Unexpected LLM response shape") from exc

        if not isinstance(content, str) or not content.strip():
            raise LLMError("LLM returned empty content")
        return content
