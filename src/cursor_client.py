"""Cursor Admin + AI Code Tracking API client (Basic auth KEY:)."""

from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

DEFAULT_BASE = "https://api.cursor.com"
DEFAULT_PAGE_SIZE = 1000
AI_COMMITS_MAX_PAGE_SIZE = 500


def _extract_email(ev: dict[str, Any]) -> str | None:
    email = ev.get("userEmail") or ev.get("email")
    if email:
        return str(email).strip()
    user = ev.get("user")
    if isinstance(user, dict) and user.get("email"):
        return str(user["email"]).strip()
    return None


def _to_cents(value: Any) -> float:
    """chargedCents may be int or fractional float."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


class CursorClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE,
        page_size: int = DEFAULT_PAGE_SIZE,
        timeout: int = 120,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.page_size = page_size
        self.commits_page_size = min(page_size, AI_COMMITS_MAX_PAGE_SIZE)
        self.timeout = timeout
        self._session = requests.Session()
        # Basic auth with empty password: -u KEY:
        self._session.auth = (api_key, "")
        self._session.headers.update({"Content-Type": "application/json"})

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        resp = self._session.post(url, json=body, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        resp = self._session.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def spend_by_email(
        self, start_ms: int, end_ms: int
    ) -> dict[str, dict[str, Any]]:
        """Sum chargedCents per userEmail for the period (paginated aggregate).

        Returns {email_lower: {"email": str, "spend_cents": float, "name": str|None}}.
        Falls back to /teams/spend if filtered-usage-events yields nothing usable.
        """
        try:
            by_email = self._aggregate_usage_spend(start_ms, end_ms)
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else "?"
            logger.warning(
                "filtered-usage-events failed (%s); trying /teams/spend fallback",
                code,
            )
            return self._spend_fallback()

        if not by_email:
            logger.warning(
                "filtered-usage-events returned no spend rows; trying /teams/spend"
            )
            return self._spend_fallback()
        return by_email

    def _aggregate_usage_spend(
        self, start_ms: int, end_ms: int
    ) -> dict[str, dict[str, Any]]:
        by_email: dict[str, dict[str, Any]] = {}
        page = 1
        total_events = 0
        while True:
            body = {
                "startDate": start_ms,
                "endDate": end_ms,
                "page": page,
                "pageSize": self.page_size,
            }
            data = self._post("/teams/filtered-usage-events", body)
            batch = (
                data.get("usageEvents")
                or data.get("events")
                or data.get("filteredUsageEvents")
                or []
            )
            if not isinstance(batch, list):
                batch = []
            for ev in batch:
                email = _extract_email(ev)
                if not email:
                    continue
                email_l = email.lower()
                cents = ev.get("chargedCents")
                if cents is None:
                    cents = ev.get("chargeCents") or ev.get("spendCents") or 0
                cents_f = _to_cents(cents)
                name = ev.get("userName") or ev.get("name")
                entry = by_email.setdefault(
                    email_l, {"email": email, "spend_cents": 0.0, "name": None}
                )
                entry["spend_cents"] += cents_f
                if name and not entry["name"]:
                    entry["name"] = str(name)
            total_events += len(batch)

            pag = (
                data.get("pagination")
                if isinstance(data.get("pagination"), dict)
                else {}
            )
            has_next = pag.get("hasNextPage")
            num_pages = pag.get("numPages") or data.get("totalPages")
            if has_next is False:
                break
            if num_pages is not None and page >= int(num_pages):
                break
            if has_next is True:
                page += 1
            elif len(batch) < self.page_size:
                break
            else:
                page += 1
            if page % 25 == 0:
                logger.info(
                    "usage spend progress: page %s, events %s, people %s",
                    page,
                    total_events,
                    len(by_email),
                )
            if page > 2000:
                logger.warning("usage events pagination safety stop at page 2000")
                break
        logger.info(
            "usage spend done: %s events across %s people",
            total_events,
            len(by_email),
        )
        return by_email

    def _spend_fallback(self) -> dict[str, dict[str, Any]]:
        """POST /teams/spend — current billing cycle only."""
        data = self._post("/teams/spend", {})
        members = data.get("teamMemberSpend") or data.get("members") or []
        by_email: dict[str, dict[str, Any]] = {}
        for m in members:
            email = m.get("email") or m.get("userEmail")
            if not email:
                continue
            email_s = str(email).strip()
            email_l = email_s.lower()
            cents = m.get("overallSpendCents")
            if cents is None:
                cents = m.get("spendCents") or 0
            by_email[email_l] = {
                "email": email_s,
                "spend_cents": _to_cents(cents),
                "name": m.get("name") or m.get("userName"),
                "source": "teams/spend_fallback",
            }
        return by_email

    def fetch_ai_commits(
        self, start_ms: int, end_ms: int
    ) -> list[dict[str, Any]]:
        """Paginate GET /analytics/ai-code/commits (items + totalCount).

        API enforces pageSize between 1 and 500.
        """
        commits: list[dict[str, Any]] = []
        page = 1
        page_size = self.commits_page_size
        while True:
            params = {
                "startDate": start_ms,
                "endDate": end_ms,
                "page": page,
                "pageSize": page_size,
            }
            data = self._get("/analytics/ai-code/commits", params)
            batch = (
                data.get("commits")
                or data.get("items")
                or data.get("data")
                or []
            )
            if not isinstance(batch, list):
                batch = []
            commits.extend(batch)

            total_count = data.get("totalCount")
            resp_ps = int(data.get("pageSize") or page_size)
            pag = (
                data.get("pagination")
                if isinstance(data.get("pagination"), dict)
                else {}
            )
            has_more = data.get("hasMore")
            if has_more is False:
                break
            if pag.get("hasNextPage") is False:
                break
            if total_count is not None and page * resp_ps >= int(total_count):
                break
            total_pages = data.get("totalPages") or pag.get("numPages")
            if total_pages is not None and page >= int(total_pages):
                break
            if len(batch) < resp_ps:
                break
            page += 1
            if page % 5 == 0:
                logger.info(
                    "AI commits progress: page %s, commits so far %s",
                    page,
                    len(commits),
                )
            if page > 2000:
                logger.warning("AI commits pagination safety stop at page 2000")
                break
        return commits
