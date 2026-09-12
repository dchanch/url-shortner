from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.db import get_connection


class LinkRepository:
    def create_link(self, short_code: str, original_url: str, created_by: str = "system") -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        with get_connection() as conn:
            existing = conn.execute(
                "SELECT 1 FROM links WHERE short_code = ?",
                (short_code,),
            ).fetchone()
            if existing is not None:
                raise ValueError(f"The short code '{short_code}' is already taken.")

            conn.execute(
                """
                INSERT INTO links (short_code, original_url, created_at, updated_at, created_by, click_count)
                VALUES (?, ?, ?, ?, ?, 0)
                """,
                (short_code, original_url, now, now, created_by),
            )
            conn.commit()

        return {
            "short_code": short_code,
            "original_url": original_url,
            "created_at": now,
            "click_count": 0,
        }

    def get_link(self, short_code: str) -> Optional[dict[str, Any]]:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT short_code, original_url, created_at, click_count FROM links WHERE short_code = ?",
                (short_code,),
            ).fetchone()
            if row is None:
                return None
            return {
                "short_code": row["short_code"],
                "original_url": row["original_url"],
                "created_at": row["created_at"],
                "click_count": row["click_count"],
            }

    def resolve_link(self, short_code: str, user_agent: Optional[str] = None, referer: Optional[str] = None, ip_address: Optional[str] = None) -> Optional[dict[str, Any]]:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT short_code, original_url, click_count FROM links WHERE short_code = ?",
                (short_code,),
            ).fetchone()
            if row is None:
                return None

            new_count = int(row["click_count"]) + 1
            timestamp = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE links SET click_count = ?, updated_at = ? WHERE short_code = ?",
                (new_count, timestamp, short_code),
            )
            conn.execute(
                "INSERT INTO clicks (short_code, clicked_at, user_agent, referer, ip_address) VALUES (?, ?, ?, ?, ?)",
                (short_code, timestamp, user_agent, referer, ip_address),
            )
            conn.commit()

        return {
            "short_code": row["short_code"],
            "original_url": row["original_url"],
            "click_count": new_count,
        }

    def get_analytics(self, short_code: str) -> Optional[dict[str, Any]]:
        with get_connection() as conn:
            link = conn.execute(
                "SELECT short_code, original_url, click_count, created_at FROM links WHERE short_code = ?",
                (short_code,),
            ).fetchone()
            if link is None:
                return None

            click_events = conn.execute(
                "SELECT clicked_at, user_agent, referer FROM clicks WHERE short_code = ? ORDER BY clicked_at DESC LIMIT 10",
                (short_code,),
            ).fetchall()

            return {
                "short_code": link["short_code"],
                "original_url": link["original_url"],
                "created_at": link["created_at"],
                "total_clicks": int(link["click_count"]),
                "recent_events": [
                    {
                        "clicked_at": row["clicked_at"],
                        "user_agent": row["user_agent"],
                        "referer": row["referer"],
                    }
                    for row in click_events
                ],
            }

    def get_health(self) -> dict[str, Any]:
        with get_connection() as conn:
            total_links = conn.execute("SELECT COUNT(*) AS count FROM links").fetchone()["count"]
            total_clicks = conn.execute("SELECT COUNT(*) AS count FROM clicks").fetchone()["count"]
        return {
            "status": "ok",
            "total_links": total_links,
            "total_clicks": total_clicks,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
