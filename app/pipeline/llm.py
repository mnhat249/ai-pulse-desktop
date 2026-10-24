from __future__ import annotations

from typing import Any, Protocol


class LLMClient(Protocol):
    name: str

    async def complete(self, prompt: str) -> str:
        """Gửi prompt, trả về chuỗi JSON. Lỗi mạng hoặc quota thì ném exception."""
        ...


class GeminiClient:
    name = "gemini"

    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model
        self._client: Any = None

    async def complete(self, prompt: str) -> str:
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self._api_key)
        from google.genai import types

        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json", temperature=0.2
            ),
        )
        return str(response.text or "")


class GroqClient:
    name = "groq"

    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model
        self._client: Any = None

    async def complete(self, prompt: str) -> str:
        if self._client is None:
            from groq import AsyncGroq

            self._client = AsyncGroq(api_key=self._api_key)
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        return str(response.choices[0].message.content or "")
