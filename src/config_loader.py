"""Load YAML configuration for projects, OpEx people, and settings."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping in {path}")
    return data


def load_settings(config_dir: Path | None = None) -> dict[str, Any]:
    d = config_dir or CONFIG_DIR
    return _load_yaml(d / "settings.yaml")


def load_projects(config_dir: Path | None = None) -> list[dict[str, Any]]:
    d = config_dir or CONFIG_DIR
    data = _load_yaml(d / "projects.yaml")
    projects = data.get("projects") or []
    if not isinstance(projects, list):
        raise ValueError("projects.yaml: 'projects' must be a list")
    return projects


def load_opex_emails(config_dir: Path | None = None) -> set[str]:
    d = config_dir or CONFIG_DIR
    data = _load_yaml(d / "opex_people.yaml")
    emails = data.get("opex_emails") or []
    return {str(e).strip().lower() for e in emails if e and str(e).strip()}


def project_root() -> Path:
    return ROOT
