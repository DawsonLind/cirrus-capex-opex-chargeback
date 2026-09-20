# Cirrus / Tungsten — CapEx vs OpEx Chargeback Prototype

Runnable Python prototype that allocates **Cursor spend** to **CapEx projects**
using per-person **AI commit line mix**, forces **OpEx** for Support/Ops people,
and leaves unmatched spend as **Unallocated** (never silent CapEx).

## Finance story

Cirrus (customer) is running the **Tungsten** engagement on Cursor. Finance needs
a weekly chargeback that answers:

1. How much Cursor $ is **capitalizable** (CapEx) against named product repos?
2. How much is **operating expense** (Support / Ops staff)?
3. How much is still **unallocated** because there is no CapEx AI-commit evidence?

This tool pulls date-aligned usage spend and AI Code Tracking commits from the
Cursor Admin API, applies deterministic allocation rules, and writes CSV + Excel
+ a one-page PDF for `dawson.lind@x.ai`.

## Allocation rules (exact)

For each person with spend **S** in the period:

1. If email (case-insensitive) is on the OpEx list → **100% OpEx**. CapEx repos ignored.
2. Else aggregate AI lines by CapEx project from commits whose `repoName` matches a project pattern.
3. If total CapEx-matched AI lines > 0 → split **S** proportionally across those projects (**CapEx**).
4. If no CapEx-matched AI lines → entire **S → Unallocated**.
5. Empty / missing `repoName` **never** creates CapEx.
6. Commits to non-matching repos do not create CapEx; unmatched-only spend → **Unallocated**.

**AI line weight** = `tabLinesAdded + composerLinesAdded` (falls back to
`totalLinesAdded` only if tab/composer are absent).

**Coverage %** = `(CapEx + OpEx) / (CapEx + OpEx + Unallocated)`.

## Setup

```bash
cd /workspace/tungsten-capex-opex
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### API key (never commit or print)

1. In Cursor Dashboard → team settings, mint an **Admin API key**.
2. Prefer `.env` (gitignored): set `CURSOR_API_KEY=…` — loaded on CLI start.
3. Or export: `export CURSOR_API_KEY='…'`
4. Or place under `/home/box/agent-data/box-secrets.json` → `card.CURSOR_API_KEY`.

If both are set, **env wins**. A stale/invalid `CURSOR_API_KEY` in the environment
will 401 even when `box-secrets.json` is valid — unset it (`env -u CURSOR_API_KEY`)
to fall back to the secrets file.

Auth is HTTP Basic with username = key and empty password (`-u KEY:`).

### Config

| File | Purpose |
|------|---------|
| `config/projects.yaml` | CapEx projects + repo name match patterns |
| `config/opex_people.yaml` | Support/OpEx emails (**MOCK** placeholders today) |
| `config/settings.yaml` | Finance email, lookback, customer/engagement |

Edit `opex_people.yaml` to replace MOCK emails with real Cirrus Support/Ops addresses.

## Run

```bash
# Last 7 days (default lookback), skip email
python -m src.run_report --days 7 --skip-email

# Explicit range (America/Los_Angeles calendar dates; end inclusive)
python -m src.run_report --start 2026-09-12 --end 2026-09-19 --skip-email

# Custom output dir; write email draft JSON (no SMTP unless SMTP_HOST set)
python -m src.run_report --days 7 --out-dir out

# Dry-run / skip-email both skip sending
python -m src.run_report --days 7 --dry-run
```

### Outputs (`out/`)

- `capex_opex_allocation_YYYY-MM-DD.csv` — detail rows
- `capex_opex_allocation_YYYY-MM-DD.xlsx` — sheets: Detail, Summary_by_Project, Summary_by_Category, Coverage
- `one_pager_YYYY-MM-DD.pdf` — totals, coverage %, top projects, headcounts
- `email_draft_YYYY-MM-DD.json` — draft payload for Gmail wiring (unless `--skip-email`)

## Tests

```bash
pytest -q
```

## Email hook

`src/email_report.py` builds a draft and writes JSON under `out/`. Optional SMTP
via `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_FROM`.
Parent agents can load the draft JSON and create a Gmail draft to
`dawson.lind@x.ai`.

## Mock repos & Automations

See [`docs/STEP_BY_STEP.md`](docs/STEP_BY_STEP.md) for creating mock GitHub repos
and Cursor Automations when those cannot be provisioned from this box.

## Project layout

```
config/           YAML settings
src/              auth, client, allocation, reports, email, CLI
tests/            allocation unit tests
docs/             step-by-step for mocks
out/              generated reports
```

## Cloud Agents + Automation

See [docs/CLOUD_AGENT_AND_AUTOMATION.md](docs/CLOUD_AGENT_AND_AUTOMATION.md) for creating a Cloud Agents environment from this repo and the Cursor Automation that runs the chargeback report.
