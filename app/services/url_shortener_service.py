from __future__ import annotations

import secrets
from typing import Any, Optional
from urllib.parse import urlparse

from app.config import BASE_URL
from app.repositories.links import LinkRepository


class InvalidUrlError(ValueError):
    """Raised when a submitted URL is not safe to shorten."""


class InvalidSlugError(ValueError):
    """Raised when a custom short code does not meet the API contract."""


class UrlShortenerService:
    def __init__(self, repository: Optional[LinkRepository] = None) -> None:
        self.repository = repository or LinkRepository()

    @staticmethod
    def _sanitize_slug(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise InvalidSlugError("Custom slug cannot be empty.")
        if len(cleaned) < 3 or len(cleaned) > 20:
            raise InvalidSlugError("Custom slug must be between 3 and 20 characters.")
        if not all(ch.isalnum() or ch in {"-", "_"} for ch in cleaned):
            raise InvalidSlugError("Custom slug may contain only letters, numbers, '-' and '_'.")
        return cleaned

    @staticmethod
    def _is_valid_url(value: str) -> bool:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    @staticmethod
    def _generate_code() -> str:
        alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        return "".join(secrets.choice(alphabet) for _ in range(7))

    def create_link(self, long_url: str, custom_slug: Optional[str] = None, created_by: str = "system") -> dict[str, Any]:
        if not self._is_valid_url(long_url):
            raise InvalidUrlError("The URL must be a valid http or https URL.")

        slug = self._sanitize_slug(custom_slug) if custom_slug else None
        if slug is None:
            while True:
                candidate = self._generate_code()
                try:
                    record = self.repository.create_link(candidate, long_url, created_by)
                    slug = record["short_code"]
                    break
                except ValueError as exc:
                    if "already taken" not in str(exc):
                        raise
        else:
            record = self.repository.create_link(slug, long_url, created_by)
            slug = record["short_code"]

        return {
            "short_code": slug,
            "original_url": long_url,
            "short_url": f"{BASE_URL}/{slug}",
            "created_at": record["created_at"],
            "click_count": record["click_count"],
        }

    def get_link(self, short_code: str) -> Optional[dict[str, Any]]:
        return self.repository.get_link(short_code)

    def resolve_link(
        self,
        short_code: str,
        user_agent: Optional[str] = None,
        referer: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        return self.repository.resolve_link(short_code, user_agent, referer, ip_address)

    def get_analytics(self, short_code: str) -> Optional[dict[str, Any]]:
        return self.repository.get_analytics(short_code)

    def get_health(self) -> dict[str, Any]:
        return self.repository.get_health()
