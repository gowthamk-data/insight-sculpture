"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Self, TypeVar

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator, model_validator

# Prefer project-root .env, then backend-local .env as a fallback.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_PROJECT_ROOT = _BACKEND_DIR.parent

load_dotenv(_PROJECT_ROOT / ".env")
load_dotenv(_BACKEND_DIR / ".env")


class Environment(str, Enum):
    """Runtime deployment mode."""

    DEVELOPMENT = "development"
    PRODUCTION = "production"


class LLMProvider(str, Enum):
    """Supported LLM backends for plan generation and explanations."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"


def _parse_bool(value: str | None, *, default: bool) -> bool:
    """Parse common truthy/falsey environment string values."""
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean value: {value!r}")


_EnumT = TypeVar("_EnumT", bound=Enum)


def _parse_enum(enum_cls: type[_EnumT], value: str | None, *, default: _EnumT) -> _EnumT:
    """Parse an environment variable into an enum member."""
    if value is None:
        return default
    try:
        return enum_cls(value.strip().lower())
    except ValueError as exc:
        valid = ", ".join(member.value for member in enum_cls)
        raise ValueError(
            f"Invalid value {value!r}; expected one of: {valid}"
        ) from exc


class Settings(BaseModel):
    """Validated application settings sourced from environment variables."""

    app_name: str = Field(default="Insight Sculpture")
    environment: Environment = Field(default=Environment.DEVELOPMENT)
    debug: bool = Field(default=True)

    llm_provider: LLMProvider = Field(default=LLMProvider.OPENAI)
    openai_api_key: str | None = Field(default=None)
    anthropic_api_key: str | None = Field(default=None)

    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8000, ge=1, le=65535)

    @field_validator("openai_api_key", "anthropic_api_key", mode="before")
    @classmethod
    def _empty_string_to_none(cls, value: object) -> str | None:
        """Treat blank API key strings as unset."""
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return str(value).strip() or None

    @model_validator(mode="after")
    def _validate_environment_and_api_keys(self) -> Self:
        """Enforce mode-specific defaults and required provider credentials."""
        if self.environment == Environment.PRODUCTION and self.debug:
            raise ValueError("DEBUG must be disabled when ENVIRONMENT is 'production'.")

        provider_key_map = {
            LLMProvider.OPENAI: ("OPENAI_API_KEY", self.openai_api_key),
            LLMProvider.ANTHROPIC: ("ANTHROPIC_API_KEY", self.anthropic_api_key),
        }
        env_name, api_key = provider_key_map[self.llm_provider]
        if not api_key:
            raise ValueError(
                f"{env_name} is required when LLM_PROVIDER is '{self.llm_provider.value}'."
            )

        return self

    @property
    def is_development(self) -> bool:
        """Return True when running in development mode."""
        return self.environment == Environment.DEVELOPMENT

    @property
    def is_production(self) -> bool:
        """Return True when running in production mode."""
        return self.environment == Environment.PRODUCTION

    @property
    def active_api_key(self) -> str:
        """Return the API key for the configured LLM provider."""
        if self.llm_provider == LLMProvider.OPENAI:
            if self.openai_api_key is None:
                raise RuntimeError("OpenAI API key is not configured.")
            return self.openai_api_key

        if self.anthropic_api_key is None:
            raise RuntimeError("Anthropic API key is not configured.")
        return self.anthropic_api_key

    @classmethod
    def from_env(cls) -> Self:
        """Build settings from the current process environment."""
        environment = _parse_enum(
            Environment,
            os.getenv("ENVIRONMENT"),
            default=Environment.DEVELOPMENT,
        )
        debug_default = environment == Environment.DEVELOPMENT

        port_raw = os.getenv("PORT", "8000")
        try:
            port = int(port_raw)
        except ValueError as exc:
            raise ValueError(f"PORT must be an integer; got {port_raw!r}") from exc

        return cls(
            app_name=os.getenv("APP_NAME", "Insight Sculpture"),
            environment=environment,
            debug=_parse_bool(os.getenv("DEBUG"), default=debug_default),
            llm_provider=_parse_enum(
                LLMProvider,
                os.getenv("LLM_PROVIDER"),
                default=LLMProvider.OPENAI,
            ),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
            host=os.getenv("HOST", "127.0.0.1"),
            port=port,
        )


@lru_cache
def get_settings() -> Settings:
    """Return a cached, validated Settings instance."""
    return Settings.from_env()
