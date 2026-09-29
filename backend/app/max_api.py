from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime, timezone
from urllib.parse import parse_qsl

import httpx

from .config import settings


class MaxAuthError(ValueError):
    pass


def verify_init_data(raw: str, bot_token: str, *, now_seconds: int | None = None) -> dict:
    if not bot_token or not raw or len(raw) > 8192:
        raise MaxAuthError("Missing MAX launch data")
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
        fields = dict(pairs)
        if len(pairs) != len(fields) or len([key for key, _ in pairs if key == "hash"]) != 1:
            raise MaxAuthError("Duplicate MAX launch parameter")
        signature = fields.pop("hash")
        if not re.fullmatch(r"[a-fA-F0-9]{64}", signature):
            raise MaxAuthError("Invalid MAX signature")
        launch_params = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
        secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret, launch_params.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature.lower()):
            raise MaxAuthError("Invalid MAX signature")
        current = now_seconds if now_seconds is not None else int(datetime.now(timezone.utc).timestamp())
        auth_date = int(fields["auth_date"])
        if auth_date > current + 60 or current - auth_date > 3600:
            raise MaxAuthError("Expired MAX launch data")
        user = json.loads(fields["user"])
        if not isinstance(user, dict) or not isinstance(user.get("id"), int) or user["id"] <= 0:
            raise MaxAuthError("Invalid MAX user")
        return user
    except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
        if isinstance(exc, MaxAuthError):
            raise
        raise MaxAuthError("Invalid MAX launch data") from exc


def app_link(payload: str | None = None) -> str | None:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", settings.max_bot_name):
        return None
    if payload and not re.fullmatch(r"[A-Za-z0-9_-]{1,512}", payload):
        return None
    suffix = f"={payload}" if payload else ""
    return f"https://max.ru/{settings.max_bot_name}?startapp{suffix}"


def plan_link(plan_id: str) -> str | None:
    return app_link(f"plan_{plan_id.replace('-', '_')}")


class TemporaryMaxError(Exception):
    pass


class PermanentMaxError(Exception):
    pass


class UncertainMaxError(Exception):
    pass


def send_message(max_user_id: str, message: str, *, plan_id: str | None = None) -> tuple[str, str | None]:
    if settings.use_mock_max:
        return "simulated", None
    if not settings.max_token:
        raise PermanentMaxError("MAX_TOKEN missing")
    link = plan_link(plan_id) if plan_id else None
    body = {"text": message + (f"\n{link}" if link else "")}
    try:
        response = httpx.post(
            "https://platform-api2.max.ru/messages",
            params={"user_id": max_user_id},
            headers={"Authorization": settings.max_token},
            json=body,
            timeout=10,
        )
    except httpx.TimeoutException as exc:
        raise UncertainMaxError("MAX request timed out") from exc
    except httpx.TransportError as exc:
        raise TemporaryMaxError("MAX transport error") from exc
    if response.status_code == 429 or response.status_code >= 500:
        raise TemporaryMaxError(f"MAX HTTP {response.status_code}")
    if response.status_code >= 400:
        raise PermanentMaxError(f"MAX HTTP {response.status_code}")
    result = response.json()
    return "sent", str(result.get("message", {}).get("body", {}).get("mid") or "") or None
