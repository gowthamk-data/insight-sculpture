"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Self

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


def _parse_enum(enum_cls: type[Enum], value: str | None, *, default: Enum) -> Enum:
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

    gemini_api_key: str | None = Field(default=None)

    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8000, ge=1, le=65535)

    @field_validator("gemini_api_key", mode="before")
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

        if not self.gemini_api_key:
            raise ValueError(
                "GEMINI_API_KEY is required for Gemini LLM provider."
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
            gemini_api_key=os.getenv("GEMINI_API_KEY"),
            host=os.getenv("HOST", "127.0.0.1"),
            port=port,
        )


@lru_cache
def get_settings() -> Settings:
    """Return a cached, validated Settings instance."""
    return Settings.from_env()