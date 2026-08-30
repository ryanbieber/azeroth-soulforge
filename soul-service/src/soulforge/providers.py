"""Server-side inference provider adapters and credential protection."""

from __future__ import annotations

from base64 import urlsafe_b64encode
from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from cryptography.fernet import Fernet, InvalidToken


@dataclass(frozen=True)
class InferenceResult:
    text: str
    usage: dict[str, int]


class SecretCipher:
    """Encrypt provider secrets with an installation-specific master value."""

    def __init__(self, master: str) -> None:
        if len(master) < 24:
            raise ValueError("SOULFORGE_SECRETS_KEY must contain at least 24 characters")
        self._fernet = Fernet(urlsafe_b64encode(sha256(master.encode()).digest()))

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode()).decode()
        except InvalidToken as error:
            raise ValueError("provider credential cannot be decrypted with this installation key") from error


class ProviderGateway:
    """Normalize text generation and token usage across supported providers."""

    def __init__(self, cipher: SecretCipher) -> None:
        self.cipher = cipher

    def generate(
        self,
        profile: dict[str, Any],
        model: str,
        prompt: str,
        temperature: float,
        max_tokens: int,
        *,
        timeout: int = 120,
    ) -> InferenceResult:
        kind = profile["kind"]
        key = self.cipher.decrypt(profile["secret_ciphertext"]) if profile.get("secret_ciphertext") else ""
        if kind == "ollama":
            return self._ollama(profile, model, prompt, temperature, max_tokens, timeout)
        if kind == "openai":
            return self._openai(profile, key, model, prompt, temperature, max_tokens, timeout)
        if kind == "anthropic":
            return self._anthropic(profile, key, model, prompt, temperature, max_tokens, timeout)
        if kind == "gemini":
            return self._gemini(profile, key, model, prompt, temperature, max_tokens, timeout)
        if kind == "openai_compatible":
            return self._compatible(profile, key, model, prompt, temperature, max_tokens, timeout)
        raise ValueError(f"unsupported provider kind: {kind}")

    @staticmethod
    def _request(url: str, body: dict[str, Any], headers: dict[str, str], timeout: int) -> dict[str, Any]:
        request = Request(
            url,
            data=json.dumps(body, separators=(",", ":")).encode(),
            headers={"Content-Type": "application/json", **headers},
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except HTTPError as error:
            raise RuntimeError(f"provider returned HTTP {error.code}") from None
        except URLError as error:
            raise RuntimeError(f"provider connection failed: {type(error.reason).__name__}") from None

    def _ollama(self, profile: dict[str, Any], model: str, prompt: str,
                temperature: float, max_tokens: int, timeout: int) -> InferenceResult:
        payload = self._request(
            f"{profile['base_url'].rstrip('/')}/api/chat",
            {
                "model": model,
                "stream": False,
                "think": False,
                "messages": [{"role": "user", "content": prompt}],
                "options": {"temperature": temperature, "num_predict": max_tokens},
            },
            {},
            timeout,
        )
        return InferenceResult(
            payload["message"]["content"].strip(),
            self._usage(payload.get("prompt_eval_count"), payload.get("eval_count")),
        )

    def _openai(self, profile: dict[str, Any], key: str, model: str, prompt: str,
                temperature: float, max_tokens: int, timeout: int) -> InferenceResult:
        payload = self._request(
            f"{profile['base_url'].rstrip('/')}/v1/responses",
            {"model": model, "input": prompt, "temperature": temperature,
             "max_output_tokens": max_tokens},
            {"Authorization": f"Bearer {key}"},
            timeout,
        )
        text = payload.get("output_text") or self._openai_output_text(payload)
        usage = payload.get("usage") or {}
        details = usage.get("input_tokens_details") or {}
        return InferenceResult(text.strip(), self._usage(
            usage.get("input_tokens"), usage.get("output_tokens"),
            cached=details.get("cached_tokens"),
            reasoning=(usage.get("output_tokens_details") or {}).get("reasoning_tokens"),
        ))

    def _anthropic(self, profile: dict[str, Any], key: str, model: str, prompt: str,
                   temperature: float, max_tokens: int, timeout: int) -> InferenceResult:
        payload = self._request(
            f"{profile['base_url'].rstrip('/')}/v1/messages",
            {"model": model, "max_tokens": max_tokens, "temperature": temperature,
             "messages": [{"role": "user", "content": prompt}]},
            {"x-api-key": key, "anthropic-version": "2023-06-01"},
            timeout,
        )
        text = "".join(block.get("text", "") for block in payload.get("content", [])
                       if block.get("type") == "text")
        usage = payload.get("usage") or {}
        cached = int(usage.get("cache_read_input_tokens") or 0)
        return InferenceResult(text.strip(), self._usage(
            usage.get("input_tokens"), usage.get("output_tokens"), cached=cached,
        ))

    def _gemini(self, profile: dict[str, Any], key: str, model: str, prompt: str,
                temperature: float, max_tokens: int, timeout: int) -> InferenceResult:
        payload = self._request(
            f"{profile['base_url'].rstrip('/')}/v1beta/models/{quote(model, safe='')}:generateContent?key={quote(key, safe='')}",
            {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
            },
            {},
            timeout,
        )
        candidates = payload.get("candidates") or []
        parts = ((candidates[0].get("content") or {}).get("parts") or []) if candidates else []
        text = "".join(part.get("text", "") for part in parts)
        usage = payload.get("usageMetadata") or {}
        return InferenceResult(text.strip(), self._usage(
            usage.get("promptTokenCount"), usage.get("candidatesTokenCount"),
            cached=usage.get("cachedContentTokenCount"), reasoning=usage.get("thoughtsTokenCount"),
        ))

    def _compatible(self, profile: dict[str, Any], key: str, model: str, prompt: str,
                    temperature: float, max_tokens: int, timeout: int) -> InferenceResult:
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        payload = self._request(
            f"{profile['base_url'].rstrip('/')}/v1/chat/completions",
            {"model": model, "messages": [{"role": "user", "content": prompt}],
             "temperature": temperature, "max_tokens": max_tokens},
            headers,
            timeout,
        )
        usage = payload.get("usage") or {}
        details = usage.get("prompt_tokens_details") or {}
        return InferenceResult(
            payload["choices"][0]["message"]["content"].strip(),
            self._usage(usage.get("prompt_tokens"), usage.get("completion_tokens"),
                        cached=details.get("cached_tokens")),
        )

    @staticmethod
    def _openai_output_text(payload: dict[str, Any]) -> str:
        chunks: list[str] = []
        for item in payload.get("output") or []:
            for content in item.get("content") or []:
                if content.get("type") == "output_text":
                    chunks.append(content.get("text", ""))
        return "".join(chunks)

    @staticmethod
    def _usage(input_tokens: Any, output_tokens: Any, *, cached: Any = 0,
               reasoning: Any = 0) -> dict[str, int]:
        values = {
            "input_tokens": max(int(input_tokens or 0), 0),
            "cached_input_tokens": max(int(cached or 0), 0),
            "reasoning_tokens": max(int(reasoning or 0), 0),
            "output_tokens": max(int(output_tokens or 0), 0),
        }
        values["total_tokens"] = values["input_tokens"] + values["output_tokens"] + values["reasoning_tokens"]
        return values
