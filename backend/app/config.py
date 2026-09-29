from __future__ import annotations

import os
from dataclasses import dataclass


def flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes"}


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./delo.db")
    public_app_url: str = os.getenv("PUBLIC_APP_URL", "http://localhost:5173")
    cors_origins: tuple[str, ...] = tuple(x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if x.strip())
    max_token: str = os.getenv("MAX_TOKEN", "")
    max_bot_name: str = os.getenv("MAX_BOT_NAME", "")
    max_webhook_secret: str = os.getenv("MAX_WEBHOOK_SECRET", "")
    use_mock_max: bool = flag("USE_MOCK_MAX", True)
    dev_auth_enabled: bool = flag("DEV_AUTH_ENABLED")
    seed_demo: bool = flag("SEED_DEMO")
    reminder_demo_enabled: bool = flag("REMINDER_DEMO_ENABLED")
    demo_base_date: str = os.getenv("DEMO_BASE_DATE", "")
    session_secret: str = os.getenv("SESSION_SECRET", "")

    def validate(self) -> None:
        if self.app_env == "production":
            if self.dev_auth_enabled or self.use_mock_max or self.seed_demo:
                raise RuntimeError("Demo authentication, mock MAX and demo seed are forbidden in production")
            if not (self.max_token and self.max_bot_name and self.max_webhook_secret and self.session_secret):
                raise RuntimeError("MAX_TOKEN, MAX_BOT_NAME, MAX_WEBHOOK_SECRET and SESSION_SECRET are required")
            if not self.public_app_url.startswith("https://") or any(not x.startswith("https://") for x in self.cors_origins):
                raise RuntimeError("HTTPS URLs are required in production")
            if not self.database_url.startswith("postgresql+psycopg://"):
                raise RuntimeError("PostgreSQL is required in production")


settings = Settings()
