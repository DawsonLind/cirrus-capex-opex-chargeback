# Step-by-step: Mock CapEx repos + Cursor Automations

Use this when the parent agent cannot create GitHub repositories or Cursor
Automations from the box. Goal: produce AI commit traffic on CapEx-pattern
repos so the chargeback prototype can allocate spend to CapEx projects.

## 1. Create mock GitHub repositories

Under a Cirrus (or demo) GitHub org, create empty repos whose **names** match
`config/projects.yaml` patterns (substring match, case-insensitive):

| Project        | Suggested repo names                         |
|----------------|----------------------------------------------|
| Tungsten       | `tungsten-frontend`, `tungsten-backend`      |
| LMS            | `lms-frontend`, `lms-backend`                |
| Payments       | `payments-service`                           |
| Data Platform  | `data-platform`                              |

Notes:

- `owner/tungsten-frontend` and bare `tungsten-frontend` both match.
- Do **not** rely on empty `repoName` — the allocator treats empty as Unallocated.
- Keep repos private if they are only for chargeback demos.

### Minimal seed commit (optional)

```bash
gh repo create YOUR_ORG/tungsten-frontend --private --clone
cd tungsten-frontend
echo "# Tungsten Frontend (chargeback mock)" > README.md
git add README.md && git commit -m "chore: seed for CapEx chargeback demo"
git push -u origin main
```

Repeat for each CapEx pattern repo.

## 2. Connect repos to Cursor

1. Open Cursor → Settings → Integrations / GitHub.
2. Grant the org or individual repos access so Cloud Agents / Automations can
   clone them.
3. Confirm team members who should generate CapEx evidence have access.

## 3. Create a Cursor Automation (demo traffic)

Purpose: generate commits with Tab/Composer AI lines attributed to CapEx repos.

Suggested automation sketch:

1. **Trigger**: Schedule (e.g. daily) or manual “Run now”.
2. **Repo**: `YOUR_ORG/tungsten-frontend` (and siblings).
3. **Prompt**: Ask the agent to make a small, reversible change (docs typo,
   comment, or changelog line) and commit with a clear message like
   `chore(chargeback-demo): noop for AI tracking`.
4. **Guardrails**: branch protection + require PR review for non-demo orgs;
   for pure mocks, allow direct commit to a `chargeback-demo` branch.

After runs, verify in Cursor Admin → **AI Code Tracking** / Analytics that
commits show non-empty `repoName` and non-zero `tabLinesAdded` /
`composerLinesAdded`.

## 4. Wire OpEx people

1. Edit `config/opex_people.yaml`.
2. Replace MOCK emails (`*@cirrus.example`, `*+opex-mock@cursor.sh`) with real
   Support / Ops addresses.
3. Re-run `python -m src.run_report --days 7 --skip-email`.

People on this list always land in **OpEx**, even if they commit to CapEx repos.

## 5. Validate end-to-end

```bash
cd /workspace/tungsten-capex-opex
source .venv/bin/activate
pytest -q
python -m src.run_report --days 7 --skip-email
```

Check `out/one_pager_*.pdf` and Coverage sheet:

- CapEx > 0 only when CapEx-pattern AI lines exist.
- Unallocated > 0 is expected when spend lacks CapEx evidence (not a bug).
- Empty `repoName` commits increase Unallocated risk — fix Automations / Git
  remotes if you see many empties in the log.

## 6. Email to finance

Without SMTP:

```bash
python -m src.run_report --days 7   # writes out/email_draft_*.json
```

Parent wires Gmail: create draft to `dawson.lind@x.ai` using that JSON + attach
CSV/XLSX/PDF.

With SMTP:

```bash
export SMTP_HOST=smtp.example.com SMTP_USER=… SMTP_PASSWORD=… SMTP_FROM=…
python -m src.run_report --days 7
```

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| All Unallocated | No CapEx-pattern commits / empty repoNames | Fix repo names + Automations |
| Coverage 0% | Same as above, or zero spend | Check API key team + date range |
| Spend fallback warning | `filtered-usage-events` empty/failed | Confirm Admin API access; `/teams/spend` is billing-cycle only |
| OpEx missing | Email not in list / case mismatch | Update `opex_people.yaml` (match is case-insensitive) |
