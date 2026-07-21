"""Gemini client for communicating with Google's Gemini API.

This module provides the only LLM client implementation, using the official
google-genai SDK for all text, JSON, and streaming operations.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Iterator

from google import genai
from google.genai import types as genai_types
from google.genai.errors import ClientError, ServerError
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

# Retry configuration
MAX_RETRIES = 3
INITIAL_RETRY_DELAY = 1.0  # seconds
RETRY_BACKOFF_MULTIPLIER = 2.0


class LLMError(Exception):
    """Base exception for Gemini client errors."""

    pass


class AuthenticationError(LLMError):
    """Raised when API authentication fails."""

    pass


class RateLimitError(LLMError):
    """Raised when API rate limit is exceeded."""

    pass


class NetworkError(LLMError):
    """Raised when network communication fails."""

    pass


class TimeoutError(LLMError):
    """Raised when API request times out."""

    pass


class EmptyResponseError(LLMError):
    """Raised when Gemini returns empty or null content."""

    pass


class InvalidResponseError(LLMError):
    """Raised when Gemini response is malformed or invalid."""

    pass


class StructuredValidationError(LLMError):
    """Raised when structured output fails Pydantic validation."""

    pass


class GeminiClient:
    """Client for communicating with Google Gemini's API.

    This class manages all communication with the Gemini API using the official
    google-genai SDK. It implements retry logic with exponential backoff for
    transient errors and converts SDK exceptions into application exceptions.

    The client is initialized once and reused for all requests to avoid
    unnecessary overhead.
    """

    DEFAULT_MODEL = "models/gemini-3.1-flash-lite"
    DEFAULT_TIMEOUT = 60.0  # seconds
    DEFAULT_TEMPERATURE = 0.7

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ) -> None:
        """Initialize the Gemini client.

        Args:
            api_key: Gemini API key. If None, loads from GEMINI_API_KEY env.
            model: Model name to use. If None, loads from GEMINI_MODEL env or default.
            timeout: Request timeout in seconds. If None, uses default.

        Raises:
            ValueError: If API key is not configured.
        """
        # Load configuration
        self._api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self._api_key:
            raise ValueError("GEMINI_API_KEY is required. Set it in environment variables.")

        self._model = model or self._get_model_from_settings()
        self._timeout = timeout if timeout is not None else self.DEFAULT_TIMEOUT

        # Initialize Gemini client once
        self._client = genai.Client(api_key=self._api_key)

    def _get_model_from_settings(self) -> str:
        """Get model name from environment settings or use default."""
        model_from_env = os.getenv("GEMINI_MODEL")
        if model_from_env:
            return model_from_env.strip()
        return self.DEFAULT_MODEL

    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int | None = None,
    ) -> str:
        """Generate text from Gemini with retry logic.

        Args:
            system_prompt: System-level instructions for the LLM.
            user_prompt: User query or input for the LLM.
            temperature: Sampling temperature (0.0 to 2.0).
            max_tokens: Maximum tokens to generate.

        Returns:
            The generated text content as a string.

        Raises:
            AuthenticationError: If API key is invalid.
            RateLimitError: If rate limit is exceeded.
            NetworkError: If network communication fails.
            TimeoutError: If request times out.
            EmptyResponseError: If LLM returns empty content.
            InvalidResponseError: If response structure is unexpected.
            LLMError: For other LLM-related errors.
        """
        messages = self._build_messages(system_prompt, user_prompt)

        def _call() -> str:
            response = self._call_chat_completion(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return self._validate_text_response(response)

        return self._retry_with_backoff(_call)

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> BaseModel:
        """Generate structured JSON output with retry logic.

        Args:
            system_prompt: System-level instructions for the LLM.
            user_prompt: User query or input for the LLM.
            response_model: Pydantic model class for structured output validation.
            temperature: Sampling temperature (0.0 to 2.0).

        Returns:
            An instance of the response_model with validated data.

        Raises:
            AuthenticationError: If API key is invalid.
            RateLimitError: If rate limit is exceeded.
            NetworkError: If network communication fails.
            TimeoutError: If request times out.
            EmptyResponseError: If LLM returns empty content.
            InvalidResponseError: If response is malformed.
            StructuredValidationError: If output fails Pydantic validation.
            LLMError: For other LLM-related errors.
        """
        messages = self._build_messages(system_prompt, user_prompt)

        def _call() -> BaseModel:
            response = self._call_structured_completion(
                messages=messages,
                response_model=response_model,
                temperature=temperature,
            )
            return self._validate_structured_response(response, response_model)

        return self._retry_with_backoff(_call)

    def stream_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> Iterator[str]:
        """Stream text chunks from Gemini with retry logic.

        Args:
            system_prompt: System-level instructions for the LLM.
            user_prompt: User query or input for the LLM.
            temperature: Sampling temperature (0.0 to 2.0).

        Yields:
            Incremental text chunks as they are generated by the LLM.

        Raises:
            AuthenticationError: If API key is invalid.
            RateLimitError: If rate limit is exceeded.
            NetworkError: If network communication fails.
            TimeoutError: If request times out.
            LLMError: For other LLM-related errors.
        """
        messages = self._build_messages(system_prompt, user_prompt)

        def _call() -> Iterator[str]:
            return self._call_chat_completion_stream(
                messages=messages,
                temperature=temperature,
            )

        stream = self._retry_with_backoff(_call)

        for chunk in stream:
            content = self._extract_stream_content(chunk)
            if content:
                yield content

    def _build_messages(
        self, system_prompt: str, user_prompt: str
    ) -> list[dict[str, str]]:
        """Construct chat messages for the Gemini API.

        Args:
            system_prompt: System-level instructions.
            user_prompt: User query or input.

        Returns:
            List of message dictionaries in the format expected by the API.
        """
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def _call_chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int | None,
    ) -> Any:
        """Call the Gemini API for non-streaming text generation.

        Args:
            messages: List of message dictionaries.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.

        Returns:
            Gemini response object.

        Raises:
            RuntimeError: If client is not initialized.
            Propagates Gemini SDK exceptions for handling by _retry_with_backoff.
        """
        if self._client is None:
            raise RuntimeError("Gemini client is not initialized.")

        system_instruction, contents = self._translate_messages(messages)

        config = genai_types.GenerateContentConfig(
            temperature=temperature,
        )

        if system_instruction:
            config.system_instruction = system_instruction

        if max_tokens is not None:
            config.max_output_tokens = max_tokens

        return self._client.models.generate_content(
            model=self._model,
            contents=contents,
            config=config,
        )

    def _call_structured_completion(
        self,
        messages: list[dict[str, str]],
        response_model: type[BaseModel],
        temperature: float,
    ) -> Any:
        """Call the Gemini API for JSON-structured output.

        Strategy: request JSON output from Gemini via
        ``response_mime_type="application/json"``, then validate the
        response text against the provided Pydantic model on the client
        side.

        Args:
            messages: List of message dictionaries.
            response_model: Pydantic model for structured output (used for
                client-side validation, NOT sent to the API).
            temperature: Sampling temperature.

        Returns:
            Gemini response object with text content that will be parsed
            into JSON by _validate_structured_response.

        Raises:
            RuntimeError: If client is not initialized.
            Propagates Gemini SDK exceptions for handling by _retry_with_backoff.
        """
        if self._client is None:
            raise RuntimeError("Gemini client is not initialized.")

        system_instruction, contents = self._translate_messages(messages)

        config = genai_types.GenerateContentConfig(
            temperature=temperature,
            response_mime_type="application/json",
        )

        if system_instruction:
            config.system_instruction = system_instruction

        return self._client.models.generate_content(
            model=self._model,
            contents=contents,
            config=config,
        )

    def _call_chat_completion_stream(
        self,
        messages: list[dict[str, str]],
        temperature: float,
    ) -> Any:
        """Call the Gemini API for streaming text generation.

        Args:
            messages: List of message dictionaries.
            temperature: Sampling temperature.

        Returns:
            Gemini streaming response iterator.

        Raises:
            RuntimeError: If client is not initialized.
            Propagates Gemini SDK exceptions for handling by _retry_with_backoff.
        """
        if self._client is None:
            raise RuntimeError("Gemini client is not initialized.")

        system_instruction, contents = self._translate_messages(messages)

        config = genai_types.GenerateContentConfig(
            temperature=temperature,
        )

        if system_instruction:
            config.system_instruction = system_instruction

        return self._client.models.generate_content_stream(
            model=self._model,
            contents=contents,
            config=config,
        )

    def _translate_messages(
        self, messages: list[dict[str, str]]
    ) -> tuple[str | None, str | list[str]]:
        """Translate chat messages to Gemini format.

        Args:
            messages: List of message dictionaries.

        Returns:
            Tuple of (system_instruction, contents) where system_instruction
            is the system message content or None, and contents is the user
            message content (string or list of strings).
        """
        system_instruction = None
        user_messages = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_instruction = content
            else:
                user_messages.append(content)

        contents = user_messages[-1] if len(user_messages) == 1 else user_messages
        return system_instruction, contents

    def _validate_text_response(self, response: Any) -> str:
        """Extract and validate text content from a Gemini response.

        Args:
            response: Gemini response object.

        Returns:
            The validated text content.

        Raises:
            EmptyResponseError: If content is empty or missing.
            InvalidResponseError: If response structure is unexpected.
        """
        try:
            content = response.text
            if content is None or content.strip() == "":
                raise EmptyResponseError("Gemini returned empty content.")
            return content
        except (IndexError, AttributeError) as exc:
            raise InvalidResponseError(
                f"Unexpected response structure from Gemini: {exc}"
            ) from exc

    def _validate_structured_response(
        self, response: Any, response_model: type[BaseModel]
    ) -> BaseModel:
        """Validate structured response against Pydantic model.

        Prefers Gemini SDK's native parsed response when available,
        falls back to manual JSON parsing.

        Args:
            response: Raw response from the Gemini API.
            response_model: Pydantic model class for validation.

        Returns:
            Validated instance of the response_model.

        Raises:
            EmptyResponseError: If content is empty or missing.
            InvalidResponseError: If response is malformed.
            StructuredValidationError: If validation fails.
        """
        try:
            # Prefer native parsed response from Gemini SDK
            if hasattr(response, "parsed") and response.parsed is not None:
                try:
                    return response_model.model_validate(response.parsed)
                except ValidationError as exc:
                    raise StructuredValidationError(
                        f"Failed to validate structured output: {exc}"
                    ) from exc

            # Fallback: parse text manually, extracting only the first JSON object
            content = response.text
            if content is None or content.strip() == "":
                raise EmptyResponseError("Gemini returned empty structured content.")

            try:
                parsed_content = self._extract_first_json_object(content)
            except json.JSONDecodeError as exc:
                raise InvalidResponseError(
                    f"Gemini returned invalid JSON: {exc}"
                ) from exc

            try:
                return response_model.model_validate(parsed_content)
            except ValidationError as exc:
                raise StructuredValidationError(
                    f"Failed to validate structured output: {exc}"
                ) from exc

        except (IndexError, AttributeError) as exc:
            raise InvalidResponseError(
                f"Unexpected structured response structure from Gemini: {exc}"
            ) from exc

    def _extract_first_json_object(self, content: str) -> Any:
        """Extract the first valid JSON object from a string.

        Handles cases where the LLM appends trailing text or markdown
        after the JSON object, which causes ``json.loads`` to raise
        ``JSONDecodeError: Extra data``.

        Args:
            content: Raw response text that may contain extra content
                before or after the JSON object.

        Returns:
            Parsed Python object from the first JSON object found.

        Raises:
            json.JSONDecodeError: If no valid JSON object can be extracted.
        """
        start = content.find("{")
        if start == -1:
            raise json.JSONDecodeError("No JSON object found in response", content, 0)

        for end in range(len(content), start, -1):
            candidate = content[start:end]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue

        raise json.JSONDecodeError(
            "No valid JSON object found in response", content, start
        )

    def _extract_stream_content(self, chunk: Any) -> str:
        """Extract text content from a streaming chunk.

        Args:
            chunk: Single chunk from the Gemini streaming response.

        Returns:
            Text content from the chunk, or empty string if no content.
        """
        try:
            return chunk.text or ""
        except (IndexError, AttributeError):
            return ""

    def _retry_with_backoff[T](self, func: callable[[], T]) -> T:
        """Execute a function with exponential backoff retry logic.

        Args:
            func: Function to execute. Should return a value or raise an exception.

        Returns:
            The return value of the function.

        Raises:
            AuthenticationError: For authentication failures (no retry).
            RateLimitError: For rate limit errors (retries with backoff).
            NetworkError: For network errors (retries with backoff).
            TimeoutError: For timeout errors (retries with backoff).
            LLMError: For other errors after retries exhausted.
        """
        last_exception: Exception | None = None
        delay = INITIAL_RETRY_DELAY

        for attempt in range(MAX_RETRIES + 1):
            try:
                return func()
            except ClientError as exc:
                status_code = getattr(exc, "status_code", None)
                if status_code in (401, 403):
                    raise AuthenticationError(
                        "Gemini authentication failed. Please check your API key."
                    ) from exc
                if status_code == 429:
                    last_exception = exc
                    if attempt < MAX_RETRIES:
                        logger.warning(
                            f"Rate limit exceeded, retrying in {delay:.1f}s "
                            f"(attempt {attempt + 1}/{MAX_RETRIES})"
                        )
                        time.sleep(delay)
                        delay *= RETRY_BACKOFF_MULTIPLIER
                    else:
                        raise RateLimitError(
                            "Gemini rate limit exceeded after retries."
                        ) from exc
                else:
                    raise self._convert_exception(exc)
            except ServerError as exc:
                last_exception = exc
                if attempt < MAX_RETRIES:
                    logger.warning(
                        f"Server error, retrying in {delay:.1f}s "
                        f"(attempt {attempt + 1}/{MAX_RETRIES})"
                    )
                    time.sleep(delay)
                    delay *= RETRY_BACKOFF_MULTIPLIER
                else:
                    raise NetworkError(
                        "Failed to connect to Gemini after retries."
                    ) from exc
            except Exception as exc:
                if "timeout" in str(exc).lower():
                    last_exception = exc
                    if attempt < MAX_RETRIES:
                        logger.warning(
                            f"Timeout error, retrying in {delay:.1f}s "
                            f"(attempt {attempt + 1}/{MAX_RETRIES})"
                        )
                        time.sleep(delay)
                        delay *= RETRY_BACKOFF_MULTIPLIER
                    else:
                        raise TimeoutError(
                            "Gemini request timed out after retries."
                        ) from exc
                else:
                    raise self._convert_exception(exc)

        if last_exception:
            raise self._convert_exception(last_exception)
        raise LLMError("Unexpected error in retry logic.")

    def _convert_exception(self, exc: Exception) -> Exception:
        """Convert Gemini SDK exceptions into application exceptions.

        Args:
            exc: Original exception from the Gemini SDK.

        Returns:
            Converted application exception.

        Raises:
            AuthenticationError: For authentication failures.
            RateLimitError: For rate limit errors.
            NetworkError: For network-related errors.
            TimeoutError: For timeout errors.
            LLMError: For other errors.
        """
        if isinstance(exc, ClientError):
            status_code = getattr(exc, "status_code", None)
            if status_code in (401, 403):
                return AuthenticationError(
                    "Gemini authentication failed. Please check your API key."
                )
            return LLMError(
                f"Gemini client error: {exc}"
            )

        if isinstance(exc, ServerError):
            return NetworkError(
                "Failed to connect to Gemini. Please check your network connection."
            )

        if "timeout" in str(exc).lower():
            return TimeoutError(
                "Gemini request timed out. Please try again."
            )

        logger.error(f"Unexpected Gemini API error: {exc}", exc_info=True)
        return LLMError(
            f"An error occurred while communicating with Gemini: {exc}"
        )

    @property
    def model(self) -> str:
        """Return the configured model name."""
        return self._model

    @property
    def timeout(self) -> float:
        """Return the configured timeout in seconds."""
        return self._timeout