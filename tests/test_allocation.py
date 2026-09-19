"""Unit tests for CapEx / OpEx / Unallocated allocation rules."""

from __future__ import annotations

import pytest

from src.allocation import (
    allocate_spend,
    ai_lines_from_commit,
    match_project,
    summarize,
)

PROJECTS = [
    {
        "name": "Tungsten",
        "patterns": ["tungsten-frontend", "tungsten-backend"],
    },
    {
        "name": "LMS",
        "patterns": ["lms-frontend", "lms-backend"],
    },
    {
        "name": "Payments",
        "patterns": ["payments-service"],
    },
    {
        "name": "Data Platform",
        "patterns": ["data-platform"],
    },
]

OPEX = {
    "support.agent@cirrus.example",
    "hanna+opex-mock@cursor.sh",
}


def test_match_project_substring_and_basename():
    assert match_project("acme/tungsten-frontend", PROJECTS)[0] == "Tungsten"
    assert match_project("Tungsten-Backend", PROJECTS)[0] == "Tungsten"
    assert match_project("org/lms-frontend", PROJECTS)[0] == "LMS"
    assert match_project("payments-service", PROJECTS)[0] == "Payments"
    assert match_project("data-platform-v2", PROJECTS)[0] == "Data Platform"


def test_match_project_empty_never_capex():
    assert match_project(None, PROJECTS) == (None, None)
    assert match_project("", PROJECTS) == (None, None)
    assert match_project("   ", PROJECTS) == (None, None)


def test_match_project_unknown_repo():
    assert match_project("random-docs", PROJECTS) == (None, None)
    assert match_project("acme/other-app", PROJECTS) == (None, None)


def test_ai_lines_prefers_tab_plus_composer():
    assert (
        ai_lines_from_commit(
            {"tabLinesAdded": 10, "composerLinesAdded": 5, "totalLinesAdded": 99}
        )
        == 15
    )
    assert ai_lines_from_commit({"totalLinesAdded": 42}) == 42
    assert ai_lines_from_commit({}) == 0


def test_opex_override_ignores_capex_commits():
    spend = {
        "support.agent@cirrus.example": {
            "email": "support.agent@cirrus.example",
            "spend_cents": 10000,
            "name": "Support Agent",
        }
    }
    commits = [
        {
            "userEmail": "support.agent@cirrus.example",
            "repoName": "acme/tungsten-frontend",
            "tabLinesAdded": 100,
            "composerLinesAdded": 0,
        }
    ]
    result = allocate_spend(spend, commits, PROJECTS, OPEX)
    assert len(result.rows) == 1
    r = result.rows[0]
    assert r.category == "OpEx"
    assert r.spend_usd == 100.0
    assert r.allocation_pct == 100.0
    assert "OpEx override" in r.notes


def test_proportional_70_30_split():
    spend = {
        "dev@cirrus.example": {
            "email": "dev@cirrus.example",
            "spend_cents": 10000,
            "name": "Dev",
        }
    }
    commits = [
        {
            "userEmail": "dev@cirrus.example",
            "repoName": "org/tungsten-frontend",
            "tabLinesAdded": 70,
            "composerLinesAdded": 0,
        },
        {
            "userEmail": "dev@cirrus.example",
            "repoName": "org/lms-backend",
            "tabLinesAdded": 30,
            "composerLinesAdded": 0,
        },
    ]
    result = allocate_spend(spend, commits, PROJECTS, OPEX)
    assert len(result.rows) == 2
    by_proj = {r.project: r for r in result.rows}
    assert set(by_proj) == {"LMS", "Tungsten"}
    assert by_proj["Tungsten"].category == "CapEx"
    assert by_proj["LMS"].category == "CapEx"
    assert by_proj["Tungsten"].spend_usd == pytest.approx(70.0)
    assert by_proj["LMS"].spend_usd == pytest.approx(30.0)
    assert by_proj["Tungsten"].allocation_pct == pytest.approx(70.0)
    assert by_proj["LMS"].allocation_pct == pytest.approx(30.0)
    assert sum(r.spend_usd for r in result.rows) == pytest.approx(100.0)


def test_unallocated_when_no_capex_commits():
    spend = {
        "solo@cirrus.example": {
            "email": "solo@cirrus.example",
            "spend_cents": 5000,
            "name": "Solo",
        }
    }
    result = allocate_spend(spend, [], PROJECTS, OPEX)
    assert len(result.rows) == 1
    r = result.rows[0]
    assert r.category == "Unallocated"
    assert r.spend_usd == 50.0


def test_empty_reponame_does_not_create_capex():
    spend = {
        "ghost@cirrus.example": {
            "email": "ghost@cirrus.example",
            "spend_cents": 2000,
        }
    }
    commits = [
        {
            "userEmail": "ghost@cirrus.example",
            "repoName": "",
            "tabLinesAdded": 500,
            "composerLinesAdded": 0,
        },
        {
            "userEmail": "ghost@cirrus.example",
            "repoName": None,
            "tabLinesAdded": 100,
            "composerLinesAdded": 0,
        },
    ]
    result = allocate_spend(spend, commits, PROJECTS, OPEX)
    assert len(result.rows) == 1
    assert result.rows[0].category == "Unallocated"
    assert result.empty_repo_commit_count == 2


def test_only_nonmatching_repos_unallocated():
    spend = {
        "other@cirrus.example": {
            "email": "other@cirrus.example",
            "spend_cents": 3000,
        }
    }
    commits = [
        {
            "userEmail": "other@cirrus.example",
            "repoName": "acme/legacy-monolith",
            "tabLinesAdded": 200,
            "composerLinesAdded": 50,
        },
        {
            "userEmail": "other@cirrus.example",
            "repoName": "",
            "tabLinesAdded": 10,
            "composerLinesAdded": 0,
        },
    ]
    result = allocate_spend(spend, commits, PROJECTS, OPEX)
    assert len(result.rows) == 1
    assert result.rows[0].category == "Unallocated"
    assert result.unmatched_repo_commit_count == 1
    assert result.empty_repo_commit_count == 1


def test_case_insensitive_opex_email():
    spend = {
        "hanna+opex-mock@cursor.sh": {
            "email": "Hanna+Opex-Mock@Cursor.SH",
            "spend_cents": 100,
        }
    }
    result = allocate_spend(spend, [], PROJECTS, OPEX)
    assert result.rows[0].category == "OpEx"


def test_summarize_coverage():
    spend = {
        "a@x.com": {"email": "a@x.com", "spend_cents": 7000},
        "b@x.com": {"email": "b@x.com", "spend_cents": 3000},
        "support.agent@cirrus.example": {
            "email": "support.agent@cirrus.example",
            "spend_cents": 2000,
        },
    }
    commits = [
        {
            "userEmail": "a@x.com",
            "repoName": "tungsten-frontend",
            "tabLinesAdded": 10,
            "composerLinesAdded": 0,
        },
    ]
    result = allocate_spend(spend, commits, PROJECTS, OPEX)
    s = summarize(result.rows)
    assert s["by_category"]["CapEx"] == pytest.approx(70.0)
    assert s["by_category"]["OpEx"] == pytest.approx(20.0)
    assert s["by_category"]["Unallocated"] == pytest.approx(30.0)
    # coverage = (70+20)/120 = 75%
    assert s["coverage_pct"] == pytest.approx(75.0)
    assert s["opex_headcount"] == 1
    assert s["unallocated_headcount"] == 1
    assert s["capex_headcount"] == 1
