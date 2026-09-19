"""CLI entrypoint: CapEx vs OpEx chargeback report for Cirrus/Tungsten."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from src.allocation import allocate_spend, summarize
from src.auth import load_api_key
from src.config_loader import (
    load_opex_emails,
    load_projects,
    load_settings,
    project_root,
)
from src.cursor_client import CursorClient
from src.email_report import build_draft, send_via_smtp, write_draft_payload
from src.reports import default_output_stems, write_csv, write_pdf_one_pager, write_xlsx

PT = ZoneInfo("America/Los_Angeles")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("run_report")


def _parse_date(s: str) -> datetime:
    """Parse YYYY-MM-DD as midnight America/Los_Angeles."""
    d = datetime.strptime(s, "%Y-%m-%d").date()
    return datetime(d.year, d.month, d.day, tzinfo=PT)


def resolve_period(
    days: int | None,
    start: str | None,
    end: str | None,
    default_days: int,
) -> tuple[datetime, datetime]:
    if start and end:
        start_dt = _parse_date(start)
        end_dt = _parse_date(end)
        # Inclusive end-of-day for end date
        end_dt = end_dt + timedelta(days=1) - timedelta(milliseconds=1)
        return start_dt, end_dt
    if start or end:
        raise SystemExit("Provide both --start and --end, or use --days")
    n = days if days is not None else default_days
    end_dt = datetime.now(PT)
    start_dt = end_dt - timedelta(days=n)
    return start_dt, end_dt


def to_epoch_ms(dt: datetime) -> int:
    return int(dt.astimezone(timezone.utc).timestamp() * 1000)



def _spend_cache_path(out_dir: Path, start_ms: int, end_ms: int) -> Path:
    return out_dir / f".cache_spend_{start_ms}_{end_ms}.json"


def _load_spend_cache(path: Path) -> dict | None:
    import json
    if not path.is_file():
        return None
    try:
        with path.open() as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _save_spend_cache(path: Path, spend: dict) -> None:
    import json
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(spend, f)

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Cirrus/Tungsten CapEx vs OpEx chargeback report"
    )
    p.add_argument("--days", type=int, default=None, help="Lookback days (default from settings)")
    p.add_argument("--start", type=str, default=None, help="Start date YYYY-MM-DD (PT)")
    p.add_argument("--end", type=str, default=None, help="End date YYYY-MM-DD (PT, inclusive)")
    p.add_argument("--out-dir", type=str, default=None, help="Output directory")
    p.add_argument("--dry-run", action="store_true", help="Skip email send/draft write")
    p.add_argument("--skip-email", action="store_true", help="Skip email (same as dry-run for email)")
    p.add_argument("--config-dir", type=str, default=None, help="Override config/ directory")
    p.add_argument("--use-spend-cache", action="store_true",
                   help="Reuse cached spend JSON under out/ if present")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = project_root()
    config_dir = Path(args.config_dir) if args.config_dir else root / "config"

    settings = load_settings(config_dir)
    projects = load_projects(config_dir)
    opex_emails = load_opex_emails(config_dir)

    period_start, period_end = resolve_period(
        args.days,
        args.start,
        args.end,
        int(settings.get("default_lookback_days") or 7),
    )
    start_ms = to_epoch_ms(period_start)
    end_ms = to_epoch_ms(period_end)

    out_dir = Path(args.out_dir) if args.out_dir else root / str(settings.get("out_dir") or "out")
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info(
        "Period %s → %s (ms %s → %s)",
        period_start.isoformat(),
        period_end.isoformat(),
        start_ms,
        end_ms,
    )

    api_key = load_api_key(settings.get("secrets_path"))
    client = CursorClient(
        api_key=api_key,
        base_url=str(settings.get("api_base_url") or "https://api.cursor.com"),
        page_size=int(settings.get("page_size") or 1000),
    )

    cache_path = _spend_cache_path(out_dir, start_ms, end_ms)
    spend = None
    if args.use_spend_cache:
        spend = _load_spend_cache(cache_path)
        if spend is not None:
            logger.info("Loaded spend cache (%d people) from %s", len(spend), cache_path)
    if spend is None:
        logger.info("Fetching spend (filtered-usage-events)…")
        spend = client.spend_by_email(start_ms, end_ms)
        _save_spend_cache(cache_path, spend)
        logger.info("Spend rows: %d people (cached to %s)", len(spend), cache_path.name)
    else:
        logger.info("Spend rows: %d people", len(spend))

    logger.info("Fetching AI commits…")
    commits = client.fetch_ai_commits(start_ms, end_ms)
    logger.info("AI commits: %d", len(commits))

    empty_repos = sum(
        1
        for c in commits
        if not str(c.get("repoName") or c.get("repo") or "").strip()
    )
    if empty_repos:
        logger.warning(
            "%d commits have empty/missing repoName (will not create CapEx)",
            empty_repos,
        )

    result = allocate_spend(spend, commits, projects, opex_emails)
    summary = summarize(result.rows)

    stems = default_output_stems(out_dir, period_end)
    # Use end calendar date in PT for filenames
    end_day = period_end.astimezone(PT).date()
    csv_path = out_dir / f"capex_opex_allocation_{end_day.isoformat()}.csv"
    xlsx_path = out_dir / f"capex_opex_allocation_{end_day.isoformat()}.xlsx"
    pdf_path = out_dir / f"one_pager_{end_day.isoformat()}.pdf"

    write_csv(result.rows, csv_path, period_start, period_end)
    meta = {
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "ai_commit_count": len(commits),
        "empty_repo_commits": result.empty_repo_commit_count,
        "unmatched_repo_commits": result.unmatched_repo_commit_count,
        "spend_people": len(spend),
    }
    write_xlsx(result.rows, xlsx_path, period_start, period_end, summary, meta)

    notes = [
        f"AI commits fetched: {len(commits)}",
        f"Empty repoName commits: {result.empty_repo_commit_count}",
        f"Non-CapEx (unmatched) repo commits: {result.unmatched_repo_commit_count}",
        "AI weight = tabLinesAdded + composerLinesAdded",
    ]
    write_pdf_one_pager(
        pdf_path,
        summary,
        period_start,
        period_end,
        customer=str(settings.get("customer") or "Cirrus"),
        engagement=str(settings.get("engagement") or "Tungsten"),
        extra_notes=notes,
    )

    logger.info("Wrote %s", csv_path)
    logger.info("Wrote %s", xlsx_path)
    logger.info("Wrote %s", pdf_path)

    cats = summary["by_category"]
    logger.info(
        "Totals CapEx=$%.2f OpEx=$%.2f Unallocated=$%.2f Coverage=%.1f%%",
        cats.get("CapEx", 0),
        cats.get("OpEx", 0),
        cats.get("Unallocated", 0),
        summary["coverage_pct"],
    )

    skip_email = args.dry_run or args.skip_email
    if not skip_email:
        finance = str(settings.get("finance_email") or "dawson.lind@x.ai")
        draft = build_draft(
            to=finance,
            summary=summary,
            period_start=period_start,
            period_end=period_end,
            attachment_paths=[csv_path, xlsx_path, pdf_path],
            customer=str(settings.get("customer") or "Cirrus"),
            engagement=str(settings.get("engagement") or "Tungsten"),
        )
        draft_path = out_dir / f"email_draft_{end_day.isoformat()}.json"
        write_draft_payload(draft, draft_path)
        logger.info("Email draft payload written to %s", draft_path)

        smtp_host = os.environ.get("SMTP_HOST", "").strip()
        if smtp_host:
            try:
                send_via_smtp(
                    draft,
                    smtp_host=smtp_host,
                    smtp_port=int(os.environ.get("SMTP_PORT") or 587),
                    smtp_user=os.environ.get("SMTP_USER"),
                    smtp_password=os.environ.get("SMTP_PASSWORD"),
                    from_addr=os.environ.get("SMTP_FROM"),
                )
                logger.info("SMTP send completed to %s", finance)
            except Exception as exc:  # noqa: BLE001
                logger.error("SMTP send failed: %s (draft still saved)", exc)
        else:
            logger.info(
                "No SMTP_HOST set — draft JSON ready for Gmail wiring (parent)"
            )
    else:
        logger.info("Email skipped (--dry-run / --skip-email)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
