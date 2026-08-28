"""OpenAI-compatible ILAAS client with retries and JSON repair."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import requests

from src.config.settings import settings
from src.llm.json_utils import JSONExtractionError, parse_json_object


# Exceptions and response objects

class LLMClientError(RuntimeError):
    """Raised when the LLM provider call fails."""


@dataclass
class LLMResponse:
    content: str
    raw: dict[str, Any]
    model: str
    provider: str = "ILAAS"


# Client

class ILAASClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1200,
        timeout_seconds: int = 120,
        max_retries: int | None = None,
        retry_sleep_seconds: int | None = None,
    ) -> None:
        self.api_key = api_key or settings.ilaas_api_key
        self.base_url = (base_url or settings.ilaas_base_url).rstrip("/")
        self.model = model or settings.ilaas_model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout_seconds = timeout_seconds

        self.max_retries = (
            max_retries
            if max_retries is not None
            else getattr(settings, "retry_max_attempts", 3)
        )

        self.retry_sleep_seconds = (
            retry_sleep_seconds
            if retry_sleep_seconds is not None
            else getattr(settings, "retry_sleep_seconds", 2)
        )

        if not self.api_key:
            raise LLMClientError("Missing ILAAS API key.")

    # -----------------------------------------------------------------
    # Public methods
    # -----------------------------------------------------------------

    def list_models(self) -> list[str]:
        url = f"{self.base_url}/models"

        headers = self._headers()

        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise LLMClientError(f"Could not list models: {exc}") from exc

        data = payload.get("data", [])

        models = []

        for item in data:
            model_id = item.get("id")

            if model_id:
                models.append(model_id)

        return models

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        selected_model = model or self.model

        payload: dict[str, Any] = {
            "model": selected_model,
            "messages": messages,
            "stream": False,
            "temperature": (
                self.temperature
                if temperature is None
                else temperature
            ),
            "max_tokens": (
                self.max_tokens
                if max_tokens is None
                else max_tokens
            ),
        }

        if response_format is not None:
            payload["response_format"] = response_format

        raw = self._post_chat_with_retries(payload)

        if isinstance(raw, dict) and raw.get("object") == "error":
            raise LLMClientError(
                "LLM provider returned error object after retries: "
                f"{self._format_provider_error(raw)}"
            )

        try:
            content = raw["choices"][0]["message"]["content"]
        except Exception as exc:
            raise LLMClientError(
                f"Unexpected chat response format: {raw}"
            ) from exc

        if not isinstance(content, str):
            raise LLMClientError(
                f"Unexpected message content type: {type(content).__name__}"
            )

        return LLMResponse(
            content=content,
            raw=raw,
            model=selected_model,
            provider="ILAAS",
        )

    def chat_json(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        repair_on_fail: bool = True,
    ) -> tuple[dict[str, Any], LLMResponse, LLMResponse | None]:
        """Request JSON and optionally repair invalid output."""
        first_response = self.chat(
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        try:
            payload = parse_json_object(first_response.content)
            return payload, first_response, None

        except JSONExtractionError as first_error:
            if not repair_on_fail:
                raise first_error

            repair_messages = self._build_json_repair_messages(
                invalid_output=first_response.content,
                parse_error=str(first_error),
            )

            repair_response = self.chat(
                messages=repair_messages,
                model=model,
                max_tokens=max_tokens,
                temperature=0.0,
            )

            try:
                payload = parse_json_object(repair_response.content)
                return payload, first_response, repair_response

            except JSONExtractionError as repair_error:
                raise repair_error

    # -----------------------------------------------------------------
    # Internal HTTP methods
    # -----------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _post_chat_with_retries(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        url = f"{self.base_url}/chat/completions"
        headers = self._headers()

        last_error: Exception | None = None
        last_error_object: dict[str, Any] | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                response = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout_seconds,
                )

                # HTTP-level retryable errors.
                if response.status_code in {408, 409, 425, 429, 500, 502, 503, 504}:
                    try:
                        error_payload = response.json()
                    except Exception:
                        error_payload = {
                            "status_code": response.status_code,
                            "text": response.text[:1000],
                        }

                    last_error_object = error_payload

                    if attempt < self.max_retries:
                        self._sleep_before_retry(attempt)
                        continue

                    raise LLMClientError(
                        "Chat completion failed with retryable HTTP error "
                        f"after {self.max_retries} attempts: "
                        f"status={response.status_code}; payload={error_payload}"
                    )

                # Non-retryable HTTP error.
                response.raise_for_status()

                try:
                    raw = response.json()
                except Exception as exc:
                    last_error = exc

                    if attempt < self.max_retries:
                        self._sleep_before_retry(attempt)
                        continue

                    raise LLMClientError(
                        f"Chat completion returned non-JSON response after "
                        f"{self.max_retries} attempts: {response.text[:1000]}"
                    ) from exc

                # Provider-level error object with HTTP 200.
                if isinstance(raw, dict) and raw.get("object") == "error":
                    last_error_object = raw

                    if self._is_retryable_provider_error(raw):
                        if attempt < self.max_retries:
                            self._sleep_before_retry(attempt)
                            continue

                        raise LLMClientError(
                            "Chat completion failed with provider error "
                            f"after {self.max_retries} attempts: "
                            f"{self._format_provider_error(raw)}"
                        )

                    raise LLMClientError(
                        "Chat completion failed with non-retryable provider error: "
                        f"{self._format_provider_error(raw)}"
                    )

                return raw

            except requests.exceptions.Timeout as exc:
                last_error = exc

                if attempt < self.max_retries:
                    self._sleep_before_retry(attempt)
                    continue

                raise LLMClientError(
                    f"Chat completion failed after {self.max_retries} attempts: "
                    f"{exc}"
                ) from exc

            except requests.exceptions.ConnectionError as exc:
                last_error = exc

                if attempt < self.max_retries:
                    self._sleep_before_retry(attempt)
                    continue

                raise LLMClientError(
                    f"Chat completion failed after {self.max_retries} attempts: "
                    f"{exc}"
                ) from exc

            except requests.exceptions.RequestException as exc:
                last_error = exc

                if attempt < self.max_retries:
                    self._sleep_before_retry(attempt)
                    continue

                raise LLMClientError(
                    f"Chat completion request failed after "
                    f"{self.max_retries} attempts: {exc}"
                ) from exc

        if last_error_object is not None:
            raise LLMClientError(
                "Chat completion failed after retries: "
                f"{self._format_provider_error(last_error_object)}"
            )

        if last_error is not None:
            raise LLMClientError(
                f"Chat completion failed after retries: {last_error}"
            ) from last_error

        raise LLMClientError("Chat completion failed for unknown reason.")

    def _sleep_before_retry(self, attempt: int) -> None:
        """Sleep with exponential backoff."""
        sleep_seconds = self.retry_sleep_seconds * (2 ** (attempt - 1))
        time.sleep(sleep_seconds)

    def _is_retryable_provider_error(
        self,
        error_payload: dict[str, Any],
    ) -> bool:
        message = str(error_payload.get("message", "")).lower()
        error_type = str(error_payload.get("type", "")).lower()
        code = str(error_payload.get("code", "")).lower()

        retryable_codes = {
            "3830",
            "429",
            "500",
            "502",
            "503",
            "504",
        }

        retryable_types = {
            "internal_server_error",
            "server_error",
            "service_unavailable",
            "rate_limit_error",
            "timeout_error",
        }

        retryable_messages = [
            "service unavailable",
            "temporarily unavailable",
            "timeout",
            "timed out",
            "rate limit",
            "too many requests",
            "internal server error",
            "bad gateway",
            "gateway timeout",
        ]

        if code in retryable_codes:
            return True

        if error_type in retryable_types:
            return True

        return any(item in message for item in retryable_messages)

    def _format_provider_error(
        self,
        error_payload: dict[str, Any],
    ) -> str:
        message = error_payload.get("message", "")
        error_type = error_payload.get("type", "")
        code = error_payload.get("code", "")
        param = error_payload.get("param", "")

        return (
            f"message={message}; "
            f"type={error_type}; "
            f"code={code}; "
            f"param={param}"
        )

    # -----------------------------------------------------------------
    # JSON repair
    # -----------------------------------------------------------------

    def _build_json_repair_messages(
        self,
        invalid_output: str,
        parse_error: str,
    ) -> list[dict[str, str]]:
        system_prompt = """
You repair invalid JSON.

Rules:
- Return only one valid JSON object.
- No markdown.
- No code fences.
- Do not add explanations.
- Preserve all scientific content.
- Fix syntax only when possible.
""".strip()

        user_prompt = f"""
The following model output was intended to be a JSON object but could not be parsed.

Parse error:
{parse_error}

Invalid output:
{invalid_output}

Return only the repaired valid JSON object.
""".strip()

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
