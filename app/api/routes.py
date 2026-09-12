from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from secrets import compare_digest
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import AnyHttpUrl, BaseModel, Field

from app.config import API_KEY, RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW_SECONDS
from app.services.url_shortener_service import UrlShortenerService

router = APIRouter()
service = UrlShortenerService()


class CreateLinkRequest(BaseModel):
    long_url: AnyHttpUrl = Field(..., description="The original HTTP or HTTPS URL to shorten.")
    custom_slug: Optional[str] = Field(
        default=None,
        min_length=3,
        max_length=20,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="Optional custom short code.",
    )


class FixedWindowRateLimiter:
    def __init__(self, limit: int, window_seconds: int) -> None:
        if limit < 1 or window_seconds < 1:
            raise ValueError("Rate limit configuration must be positive.")
        self.limit = limit
        self.window_seconds = window_seconds
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> Optional[int]:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            timestamps = self._requests[key]
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()
            if len(timestamps) >= self.limit:
                return max(1, int(self.window_seconds - (now - timestamps[0])))
            timestamps.append(now)
        return None


rate_limiter = FixedWindowRateLimiter(RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW_SECONDS)


def _enforce_rate_limit(request: Request) -> None:
    client_host = request.client.host if request.client else "unknown"
    retry_after = rate_limiter.check(client_host)
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Please retry later.",
            headers={"Retry-After": str(retry_after)},
        )


def _enforce_api_key(request: Request) -> None:
    if API_KEY is not None and not compare_digest(request.headers.get("X-API-Key", ""), API_KEY):
        raise HTTPException(status_code=401, detail="A valid API key is required.")


@router.get("/health")
def health() -> dict:
    return service.get_health()


@router.post("/api/links")
def create_link(request: Request, payload: CreateLinkRequest) -> dict:
    _enforce_api_key(request)
    _enforce_rate_limit(request)
    try:
        return service.create_link(str(payload.long_url), payload.custom_slug)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/links/{short_code}")
def get_link(short_code: str) -> dict:
    record = service.get_link(short_code)
    if record is None:
        raise HTTPException(status_code=404, detail="Short code not found")
    return record


@router.get("/api/links/{short_code}/analytics")
def get_analytics(short_code: str) -> dict:
    analytics = service.get_analytics(short_code)
    if analytics is None:
        raise HTTPException(status_code=404, detail="Short code not found")
    return analytics


@router.get("/{short_code}")
def redirect_link(short_code: str):
    link = service.resolve_link(short_code)
    if link is None:
        raise HTTPException(status_code=404, detail="Short code not found")
    return RedirectResponse(url=link["original_url"], status_code=307)
