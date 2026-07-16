"""LLM provider client for communicating with configured language models."""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Iterator

from openai import OpenAI, Stream
from openai.types.chat import ChatCompletion, ChatCompletionChunk
from pydantic import BaseModel, ValidationError
from pydantic.json_schema import JsonSchemaValue

from app.config import LLMProvider, get_settings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Base exception for LLM client errors."""

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
    """Raised when LLM returns empty or null content."""

    pass


class InvalidResponseError(LLMError):
    """Raised when LLM response is malformed or invalid."""

    pass


class StructuredValidationError(LLMError):
    """Raised when structured output fails Pydantic validation."""

    pass


class LLMClient:
    """Client for communicating with configured LLM providers.

    This class manages all communication with the LLM provider. It is
    intentionally separated from analytics logic, prompt engineering,
    and FastAPI integration.

    The client is initialized once and reused for all requests to avoid
    unnecessary overhead.
    """

    # Default model names for each provider
    DEFAULT_MODELS: dict[LLMProvider, str] = {
        LLMProvider.OPENAI: "gpt-4o",
        LLMProvider.ANTHROPIC: "claude-3-5-sonnet-20240620",
        LLMProvider.GEMINI: "models/gemini-3.5-flash",
    }

    def __init__(self) -> None:
        """Initialize the LLM client with configuration from settings."""
        self._settings = get_settings()
        self._provider = self._settings.llm_provider
        self._api_key = self._settings.active_api_key
        self._model = self._get_model_name()
        self._timeout = 60.0  # Default timeout in seconds

        self._client: OpenAI | None = None
        self._initialize_client()

    def _initialize_client(self) -> None:
        """Initialize the appropriate provider client based on configuration."""
        if self._provider == LLMProvider.OPENAI:
            self._client = OpenAI(api_key=self._api_key, timeout=self._timeout)
        elif self._provider == LLMProvider.ANTHROPIC:
            # Anthropic client will be added when needed
            # For now, raise an error if Anthropic is selected
            raise NotImplementedError(
                "Anthropic provider is not yet implemented. "
                "Please use OpenAI provider or implement Anthropic support."
            )
        else:
            raise ValueError(f"Unsupported LLM provider: {self._provider}")

    def _get_model_name(self) -> str:
        """Get the model name from settings or use default."""
        # Check if there's a model setting in environment
        import os

        model_from_env = os.getenv("LLM_MODEL")
        if model_from_env:
            return model_from_env.strip()

        return self.DEFAULT_MODELS.get(self._provider, "gpt-4o")

    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        """Generate text from the LLM.

        Args:
            system_prompt: System-level instructions for the LLM.
            user_prompt: User query or input for the LLM.
            temperature: Sampling temperature (0.0 to 2.0). Lower is more deterministic.
            max_tokens: Maximum tokens to generate. None uses provider default.

        Returns:
            The generated text content as a string.

        Raises:
            AuthenticationError: If API key is invalid.
            RateLimitError: If rate limit is exceeded.
            NetworkError: If network communication fails.
            TimeoutError: If request times out.
            EmptyResponseError: If LLM returns empty content.
            InvalidResponseError: If response is malformed.
            LLMError: For other LLM-related errors.
        """
        messages = self._build_messages(system_prompt, user_prompt)

        try:
            response = self._call_chat_completion(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return self._validate_response(response)
        except Exception as exc:
            self._handle_api_error(exc)

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
        temperature: float = 0.7,
    ) -> BaseModel:
        """Generate structured JSON output validated against a Pydantic model.

        Args:
            system_prompt: System-level instructions for the LLM.
            user_prompt: User query or input for the LLM.
            response_model: Pydantic model class for structured output validation.
            temperature: Sampling temperature (0.0 to 2.0). Lower is more deterministic.

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

        try:
            response = self._call_structured_completion(
                messages=messages,
                response_model=response_model,
                temperature=temperature,
            )
            return self._validate_structured_response(response, response_model)
        except Exception as exc:
            self._handle_api_error(exc)

    def stream_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
    ) -> Iterator[str]:
        """Stream text chunks from the LLM.

        Args:
            system_prompt: System-level instructions for the LLM.
            user_prompt: User query or input for the LLM.
            temperature: Sampling temperature (0.0 to 2.0). Lower is more deterministic.

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

        try:
            stream = self._call_chat_completion_stream(
                messages=messages,
                temperature=temperature,
            )
            for chunk in stream:
                content = self._extract_stream_content(chunk)
                if content:
                    yield content
        except Exception as exc:
            self._handle_api_error(exc)

    def _build_messages(
        self, system_prompt: str, user_prompt: str
    ) -> list[dict[str, str]]:
        """Construct chat messages for the LLM API.

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
    ) -> ChatCompletion:
        """Call the chat completion API for non-streaming text generation.

        Args:
            messages: List of chat messages.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.

        Returns:
            ChatCompletion response from the API.

        Raises:
            Propagates API exceptions for handling by _handle_api_error.
        """
        if self._client is None:
            raise RuntimeError("LLM client is not initialized.")

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
        }

        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        return self._client.chat.completions.create(**kwargs)

    def _call_structured_completion(
        self,
        messages: list[dict[str, str]],
        response_model: type[BaseModel],
        temperature: float,
    ) -> Any:
        """Call the chat completion API with structured output.

        Args:
            messages: List of chat messages.
            response_model: Pydantic model for structured output.
            temperature: Sampling temperature.

        Returns:
            Structured response from the API.

        Raises:
            Propagates API exceptions for handling by _handle_api_error.
        """
        if self._client is None:
            raise RuntimeError("LLM client is not initialized.")

        # Get JSON schema from Pydantic model
        json_schema = response_model.model_json_schema()

        return self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=temperature,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": response_model.__name__,
                    "strict": True,
                    "schema": json_schema,
                },
            },
        )

    def _call_chat_completion_stream(
        self,
        messages: list[dict[str, str]],
        temperature: float,
    ) -> Stream[ChatCompletionChunk]:
        """Call the chat completion API for streaming text generation.

        Args:
            messages: List of chat messages.
            temperature: Sampling temperature.

        Returns:
            Stream of ChatCompletionChunk objects.

        Raises:
            Propagates API exceptions for handling by _handle_api_error.
        """
        if self._client is None:
            raise RuntimeError("LLM client is not initialized.")

        return self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=temperature,
            stream=True,
        )

    def _validate_response(self, response: ChatCompletion) -> str:
        """Extract and validate text content from a chat completion response.

        Args:
            response: ChatCompletion response from the API.

        Returns:
            The validated text content.

        Raises:
            EmptyResponseError: If content is empty or missing.
            InvalidResponseError: If response structure is unexpected.
        """
        try:
            content = response.choices[0].message.content
            if content is None or content.strip() == "":
                raise EmptyResponseError("LLM returned empty content.")
            return content
        except (IndexError, AttributeError) as exc:
            raise InvalidResponseError(
                f"Unexpected response structure from LLM: {exc}"
            ) from exc

    def _validate_structured_response(
        self, response: Any, response_model: type[BaseModel]
    ) -> BaseModel:
        """Validate structured response against Pydantic model.

        Args:
            response: Raw response from the API.
            response_model: Pydantic model class for validation.

        Returns:
            Validated instance of the response_model.

        Raises:
            EmptyResponseError: If content is empty or missing.
            InvalidResponseError: If response structure is unexpected.
            StructuredValidationError: If validation fails.
        """
        try:
            content = response.choices[0].message.content
            if content is None or content.strip() == "":
                raise EmptyResponseError("LLM returned empty structured content.")

            # Parse JSON content, extracting only the first JSON object
            import json as _json

            try:
                parsed_content = self._extract_first_json_object(content)
            except _json.JSONDecodeError as exc:
                raise InvalidResponseError(
                    f"LLM returned invalid JSON: {exc}"
                ) from exc

            # Validate against Pydantic model
            try:
                return response_model.model_validate(parsed_content)
            except ValidationError as exc:
                raise StructuredValidationError(
                    f"Failed to validate structured output: {exc}"
                ) from exc

        except (IndexError, AttributeError) as exc:
            raise InvalidResponseError(
                f"Unexpected structured response structure from LLM: {exc}"
            ) from exc

    def _extract_stream_content(self, chunk: ChatCompletionChunk) -> str:
        """Extract text content from a streaming chunk.

        Args:
            chunk: Single chunk from the streaming response.

        Returns:
            Text content from the chunk, or empty string if no content.
        """
        try:
            delta = chunk.choices[0].delta
            return delta.content or ""
        except (IndexError, AttributeError):
            return ""

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
        import json as _json

        start = content.find("{")
        if start == -1:
            raise _json.JSONDecodeError("No JSON object found in response", content, 0)

        for end in range(len(content), start, -1):
            candidate = content[start:end]
            try:
                return _json.loads(candidate)
            except _json.JSONDecodeError:
                continue

        raise _json.JSONDecodeError(
            "No valid JSON object found in response", content, start
        )

    def _handle_api_error(self, exc: Exception) -> None:
        """Convert provider exceptions into clean application exceptions.

        Args:
            exc: Original exception from the provider SDK.

        Raises:
            AuthenticationError: For authentication failures.
            RateLimitError: For rate limit errors.
            NetworkError: For network-related errors.
            TimeoutError: For timeout errors.
            LLMError: For other errors.
        """
        # Import OpenAI exceptions
        from openai import AuthenticationError as OpenAIAuthError
        from openai import APICONNECTIONERROR, RateLimitError as OpenAIRateLimitError

        if isinstance(exc, OpenAIAuthError):
            raise AuthenticationError(
                "LLM provider authentication failed. Please check your API key."
            ) from exc

        if isinstance(exc, OpenAIRateLimitError):
            raise RateLimitError(
                "LLM provider rate limit exceeded. Please try again later."
            ) from exc

        if isinstance(exc, APICONNECTIONERROR):
            raise NetworkError(
                "Failed to connect to LLM provider. Please check your network connection."
            ) from exc

        # Check for timeout-related errors
        if "timeout" in str(exc).lower():
            raise TimeoutError(
                "LLM provider request timed out. Please try again."
            ) from exc

        # Generic LLM error for anything else
        logger.error(f"Unexpected LLM API error: {exc}", exc_info=True)
        raise LLMError(
            f"An error occurred while communicating with the LLM provider: {exc}"
        ) from exc

    @property
    def provider(self) -> LLMProvider:
        """Return the configured LLM provider."""
        return self._provider

    @property
    def model(self) -> str:
        """Return the configured model name."""
        return self._model
