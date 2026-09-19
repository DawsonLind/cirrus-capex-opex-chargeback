"""Pure CapEx / OpEx / Unallocated allocation logic."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass
class AllocationRow:
    email: str
    name: str | None
    category: str  # CapEx | OpEx | Unallocated
    project: str
    repo_match: str
    spend_usd: float
    ai_lines: int
    allocation_pct: float
    notes: str = ""


@dataclass
class AllocationResult:
    rows: list[AllocationRow] = field(default_factory=list)
    empty_repo_commit_count: int = 0
    unmatched_repo_commit_count: int = 0


def match_project(
    repo_name: str | None, projects: list[dict[str, Any]]
) -> tuple[str | None, str | None]:
    """Return (project_name, matched_pattern) or (None, None).

    Empty / missing repoName never matches.
    Match is case-insensitive substring against full repoName and basename
    after last slash. First matching project (config order) wins.
    """
    if repo_name is None:
        return None, None
    raw = str(repo_name).strip()
    if not raw:
        return None, None

    full = raw.lower()
    basename = full.rsplit("/", 1)[-1]

    for proj in projects:
        name = proj.get("name")
        patterns = proj.get("patterns") or []
        for pat in patterns:
            p = str(pat).strip().lower()
            if not p:
                continue
            if p in full or p in basename:
                return str(name), str(pat)
    return None, None


def ai_lines_from_commit(commit: dict[str, Any]) -> int:
    """Prefer tabLinesAdded + composerLinesAdded; else totalLinesAdded."""
    tab = commit.get("tabLinesAdded")
    composer = commit.get("composerLinesAdded")
    if tab is not None or composer is not None:
        try:
            return int(tab or 0) + int(composer or 0)
        except (TypeError, ValueError):
            pass
    total = commit.get("totalLinesAdded")
    try:
        return int(total or 0)
    except (TypeError, ValueError):
        return 0


def aggregate_ai_lines_by_project(
    commits: Iterable[dict[str, Any]],
    projects: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], int, int]:
    """Per-email CapEx AI line totals.

    Returns:
      by_email: {email_lower: {
          "email": str,
          "projects": {project_name: {"ai_lines": int, "repo_match": str}},
          "total_capex_lines": int,
      }}
      empty_repo_count, unmatched_repo_count
    """
    by_email: dict[str, dict[str, Any]] = {}
    empty_repo = 0
    unmatched = 0

    for c in commits:
        email = c.get("userEmail") or c.get("email")
        if not email:
            continue
        email_l = str(email).strip().lower()
        repo = c.get("repoName") or c.get("repo") or ""
        lines = ai_lines_from_commit(c)
        project, pattern = match_project(repo, projects)

        if not str(repo).strip():
            empty_repo += 1
            continue
        if project is None:
            unmatched += 1
            continue
        if lines <= 0:
            # Still counts as CapEx-matched activity with zero weight
            entry = by_email.setdefault(
                email_l,
                {
                    "email": str(email).strip(),
                    "projects": {},
                    "total_capex_lines": 0,
                },
            )
            proj_entry = entry["projects"].setdefault(
                project, {"ai_lines": 0, "repo_match": pattern or ""}
            )
            if pattern and not proj_entry["repo_match"]:
                proj_entry["repo_match"] = pattern
            continue

        entry = by_email.setdefault(
            email_l,
            {
                "email": str(email).strip(),
                "projects": {},
                "total_capex_lines": 0,
            },
        )
        proj_entry = entry["projects"].setdefault(
            project, {"ai_lines": 0, "repo_match": pattern or ""}
        )
        proj_entry["ai_lines"] += lines
        if pattern:
            # Keep first match pattern; append if new distinct pattern
            existing = proj_entry["repo_match"]
            if pattern not in existing.split(","):
                proj_entry["repo_match"] = (
                    f"{existing},{pattern}" if existing else pattern
                )
        entry["total_capex_lines"] += lines

    return by_email, empty_repo, unmatched


def allocate_spend(
    spend_by_email: dict[str, dict[str, Any]],
    commits: list[dict[str, Any]],
    projects: list[dict[str, Any]],
    opex_emails: set[str],
) -> AllocationResult:
    """Apply CapEx / OpEx / Unallocated rules for each person with spend S.

    Rules:
    1. OpEx list → 100% OpEx (ignore CapEx repos).
    2. Else aggregate CapEx-matched AI lines by project.
    3. If total CapEx AI lines > 0 → split S proportionally.
    4. Else entire S → Unallocated.
    5. Empty/unknown repoName never creates CapEx.
    6. Non-matching repos do not create CapEx; unmatched-only → Unallocated.
    """
    ai_by_email, empty_n, unmatched_n = aggregate_ai_lines_by_project(
        commits, projects
    )
    opex_set = {e.strip().lower() for e in opex_emails}
    rows: list[AllocationRow] = []

    for email_l, spend_info in sorted(spend_by_email.items()):
        email = spend_info.get("email") or email_l
        name = spend_info.get("name")
        cents = float(spend_info.get("spend_cents") or 0)
        spend_usd = round(cents / 100.0, 4)
        if abs(spend_usd) < 1e-9 and abs(cents) < 1e-9:
            continue

        if email_l in opex_set:
            rows.append(
                AllocationRow(
                    email=email,
                    name=name,
                    category="OpEx",
                    project="OpEx / Support",
                    repo_match="",
                    spend_usd=spend_usd,
                    ai_lines=0,
                    allocation_pct=100.0,
                    notes="OpEx override list",
                )
            )
            continue

        ai_info = ai_by_email.get(email_l)
        total_lines = int(ai_info["total_capex_lines"]) if ai_info else 0

        if ai_info and total_lines > 0:
            projects_map = ai_info["projects"]
            # Proportional split; last project absorbs rounding residue
            allocated = 0.0
            items = [
                (pname, pdata)
                for pname, pdata in sorted(projects_map.items())
                if int(pdata.get("ai_lines") or 0) > 0
            ]
            for i, (pname, pdata) in enumerate(items):
                lines = int(pdata["ai_lines"])
                pct = (lines / total_lines) * 100.0
                if i == len(items) - 1:
                    usd = round(spend_usd - allocated, 4)
                else:
                    usd = round(spend_usd * (lines / total_lines), 4)
                    allocated += usd
                rows.append(
                    AllocationRow(
                        email=email,
                        name=name,
                        category="CapEx",
                        project=pname,
                        repo_match=str(pdata.get("repo_match") or ""),
                        spend_usd=usd,
                        ai_lines=lines,
                        allocation_pct=round(pct, 4),
                        notes="Proportional to CapEx AI lines (tab+composer)",
                    )
                )
            continue

        # No CapEx-matched AI lines → Unallocated
        note = "No CapEx-matched AI commit lines in period"
        if ai_info and ai_info.get("projects") and total_lines == 0:
            note = "CapEx repos seen but zero AI lines; Unallocated"
        rows.append(
            AllocationRow(
                email=email,
                name=name,
                category="Unallocated",
                project="Unallocated",
                repo_match="",
                spend_usd=spend_usd,
                ai_lines=0,
                allocation_pct=100.0,
                notes=note,
            )
        )

    return AllocationResult(
        rows=rows,
        empty_repo_commit_count=empty_n,
        unmatched_repo_commit_count=unmatched_n,
    )


def summarize(rows: list[AllocationRow]) -> dict[str, Any]:
    """Totals by category / project and coverage metrics."""
    by_category: dict[str, float] = {"CapEx": 0.0, "OpEx": 0.0, "Unallocated": 0.0}
    by_project: dict[str, float] = {}
    emails_by_cat: dict[str, set[str]] = {
        "CapEx": set(),
        "OpEx": set(),
        "Unallocated": set(),
    }

    for r in rows:
        by_category[r.category] = by_category.get(r.category, 0.0) + r.spend_usd
        by_project[r.project] = by_project.get(r.project, 0.0) + r.spend_usd
        emails_by_cat.setdefault(r.category, set()).add(r.email.lower())

    total = sum(by_category.values())
    covered = by_category.get("CapEx", 0.0) + by_category.get("OpEx", 0.0)
    coverage_pct = (covered / total * 100.0) if total > 0 else 0.0

    return {
        "by_category": {k: round(v, 4) for k, v in by_category.items()},
        "by_project": {
            k: round(v, 4)
            for k, v in sorted(by_project.items(), key=lambda x: -x[1])
        },
        "total_usd": round(total, 4),
        "coverage_pct": round(coverage_pct, 2),
        "opex_headcount": len(emails_by_cat.get("OpEx", set())),
        "unallocated_headcount": len(emails_by_cat.get("Unallocated", set())),
        "capex_headcount": len(emails_by_cat.get("CapEx", set())),
    }
