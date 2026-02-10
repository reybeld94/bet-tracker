from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken

from app.models import AppSettings

logger = logging.getLogger(__name__)
_FERNET: Fernet | None = None


@dataclass(frozen=True)
class SettingsSnapshot:
    id: int
    openai_api_key_enc: str | None
    openai_model: str
    openai_reasoning_effort: str
    auto_picks_enabled: bool
    auto_picks_concurrency: int
    auto_picks_poll_seconds: int
    auto_picks_max_retries: int
    allow_totals_default: bool


def _default_settings() -> AppSettings:
    return AppSettings(
        id=1,
        openai_api_key_enc=None,
        openai_model="gpt-5",
        openai_reasoning_effort="high",
        auto_picks_enabled=True,
        auto_picks_concurrency=2,
        auto_picks_poll_seconds=30,
        auto_picks_max_retries=2,
        allow_totals_default=False,
        updated_at_utc=datetime.now(timezone.utc),
    )


def get_or_create_settings(db) -> AppSettings:
    settings = db.query(AppSettings).filter(AppSettings.id == 1).one_or_none()
    if settings:
        return settings
    settings = _default_settings()
    db.add(settings)
    db.commit()
    db.refresh(settings)
    return settings


def snapshot_settings(settings: AppSettings) -> SettingsSnapshot:
    return SettingsSnapshot(
        id=settings.id,
        openai_api_key_enc=settings.openai_api_key_enc,
        openai_model=settings.openai_model,
        openai_reasoning_effort=settings.openai_reasoning_effort,
        auto_picks_enabled=settings.auto_picks_enabled,
        auto_picks_concurrency=settings.auto_picks_concurrency,
        auto_picks_poll_seconds=settings.auto_picks_poll_seconds,
        auto_picks_max_retries=settings.auto_picks_max_retries,
        allow_totals_default=settings.allow_totals_default,
    )


def get_fernet() -> Fernet:
    global _FERNET
    if _FERNET is not None:
        return _FERNET
    secret = (os.getenv("APP_SECRET_KEY") or "").strip()
    if not secret:
        secret = Fernet.generate_key().decode("utf-8")
        logger.warning(
            "APP_SECRET_KEY missing. Generated a temporary key: %s. "
            "Set APP_SECRET_KEY to this value to persist decryption.",
            secret,
        )
    _FERNET = Fernet(secret.encode("utf-8"))
    return _FERNET


def encrypt_api_key(api_key: str | None) -> str | None:
    if not api_key:
        return None
    fernet = get_fernet()
    return fernet.encrypt(api_key.encode("utf-8")).decode("utf-8")


def decrypt_api_key(encrypted: str | None) -> str | None:
    if not encrypted:
        return None
    fernet = get_fernet()
    try:
        return fernet.decrypt(encrypted.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        logger.error("Failed to decrypt OpenAI API key. Check APP_SECRET_KEY.")
        return None
