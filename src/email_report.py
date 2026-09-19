"""Email hook for CapEx/OpEx report — draft payload + optional SMTP.

Parent agent can wire Gmail MCP; this module never requires live send.
"""

from __future__ import annotations

import json
import smtplib
from dataclasses import asdict, dataclass
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

PT = ZoneInfo("America/Los_Angeles")


@dataclass
class EmailDraft:
    to: str
    subject: str
    body_text: str
    attachments: list[str]
    created_at: str


def build_draft(
    to: str,
    summary: dict[str, Any],
    period_start: datetime,
    period_end: datetime,
    attachment_paths: list[Path],
    customer: str = "Cirrus",
    engagement: str = "Tungsten",
) -> EmailDraft:
    cats = summary.get("by_category", {})
    subject = (
        f"[{customer}/{engagement}] CapEx vs OpEx chargeback "
        f"{period_start.date().isoformat()} → {period_end.date().isoformat()}"
    )
    body = (
        f"CapEx vs OpEx chargeback report for {customer} / {engagement}\n"
        f"Period: {period_start.date().isoformat()} → {period_end.date().isoformat()}\n\n"
        f"CapEx:       ${cats.get('CapEx', 0):,.2f}\n"
        f"OpEx:        ${cats.get('OpEx', 0):,.2f}\n"
        f"Unallocated: ${cats.get('Unallocated', 0):,.2f}\n"
        f"Total:       ${summary.get('total_usd', 0):,.2f}\n"
        f"Coverage:    {summary.get('coverage_pct', 0):.1f}%\n\n"
        f"OpEx headcount: {summary.get('opex_headcount', 0)}\n"
        f"Unallocated headcount: {summary.get('unallocated_headcount', 0)}\n\n"
        "Attachments: CSV detail, Excel workbook, PDF one-pager.\n"
        "Unallocated spend is intentional when CapEx AI commit evidence is missing.\n"
    )
    return EmailDraft(
        to=to,
        subject=subject,
        body_text=body,
        attachments=[str(p) for p in attachment_paths],
        created_at=datetime.now(PT).isoformat(),
    )


def write_draft_payload(draft: EmailDraft, path: Path) -> Path:
    """Write JSON draft for parent to pick up (Gmail create_draft hook)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(asdict(draft), f, indent=2)
    return path


def send_via_smtp(
    draft: EmailDraft,
    smtp_host: str,
    smtp_port: int = 587,
    smtp_user: str | None = None,
    smtp_password: str | None = None,
    from_addr: str | None = None,
    use_tls: bool = True,
) -> None:
    """Optional SMTP send when SMTP_* env vars are configured.

    Raises if SMTP is not configured. Prefer write_draft_payload for Gmail wiring.
    """
    if not smtp_host:
        raise RuntimeError("SMTP host not configured; use draft payload instead")

    msg = EmailMessage()
    msg["Subject"] = draft.subject
    msg["From"] = from_addr or smtp_user or "noreply@localhost"
    msg["To"] = draft.to
    msg.set_content(draft.body_text)

    for att in draft.attachments:
        p = Path(att)
        if not p.is_file():
            continue
        data = p.read_bytes()
        maintype = "application"
        subtype = "octet-stream"
        if p.suffix.lower() == ".csv":
            maintype, subtype = "text", "csv"
        elif p.suffix.lower() == ".pdf":
            maintype, subtype = "application", "pdf"
        elif p.suffix.lower() in (".xlsx", ".xls"):
            subtype = "vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        msg.add_attachment(
            data,
            maintype=maintype,
            subtype=subtype,
            filename=p.name,
        )

    with smtplib.SMTP(smtp_host, smtp_port, timeout=60) as server:
        if use_tls:
            server.starttls()
        if smtp_user and smtp_password:
            server.login(smtp_user, smtp_password)
        server.send_message(msg)
