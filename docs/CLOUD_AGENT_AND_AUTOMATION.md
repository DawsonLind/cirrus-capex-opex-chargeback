# Cloud Agent environment + Automation setup

This repo is the **chargeback tooling** repo only (not Tungsten/LMS product apps).

## 1. Secrets (required)

Never commit `CURSOR_API_KEY`.

1. Mint/confirm a **Team Admin** API key (`admin:*`) at https://cursor.com/dashboard → API Keys.
2. Add it as a secret named **`CURSOR_API_KEY`** on:
   - the **Cloud Agents environment** you create from this repo, and/or
   - the **Automation** that runs against this repo.

Auth to Cursor APIs is HTTP Basic: username = key, password empty.

## 2. Create a Cloud Agents environment from this repo

1. Open https://cursor.com/dashboard → **Cloud Agents** → **Environments** (or create from Agents when prompted).
2. Create / select an environment that includes **this repository** only.
3. Add secret `CURSOR_API_KEY` = your Team Admin key.
4. Optional install snapshot / setup command:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

5. Save the environment. You will pick it when creating the Automation.

## 3. Create the Automation

1. Go to https://cursor.com/automations → **New automation**.
2. **Name:** `Cirrus CapEx OpEx weekly chargeback`
3. **Trigger:** Manual **Run now** first; add weekly cron after it works.
4. **Repository:** this repo (single repo). Pick the Cloud Agents **environment** from step 2.
5. **Tools:** enable email (Gmail/Resend/etc. MCP) if available; disable PR creation for this job.
6. **Secret:** ensure `CURSOR_API_KEY` is available to the run.
7. **Prompt** (copy/paste):

```text
You are the Cirrus CapEx vs OpEx chargeback runner.

Working directory: this repository root.

1. Create/use .venv and `pip install -r requirements.txt` if needed.
2. Ensure CURSOR_API_KEY is set in the environment (do not print it).
3. Run:
   `python -m src.run_report --days 7`
   If email MCP/SMTP is not configured, use `--skip-email` and attach the files from `out/` in your reply, then send them to dawson.lind@x.ai with the email tool if available.
4. Summarize CapEx $, OpEx $, Unallocated $, and coverage % from the run.
5. Do not open PRs. Do not modify CapEx product repos. Do not commit secrets.
```

8. Save → **Run now**.

## 4. Config you may edit in this repo

| File | Purpose |
|------|---------|
| `config/projects.yaml` | CapEx project → repo name patterns |
| `config/opex_people.yaml` | OpEx / Support emails (replace MOCK) |
| `config/settings.yaml` | Finance email, lookback days |

## 5. Local smoke test

```bash
cp .env.example .env   # then set CURSOR_API_KEY
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q
python -m src.run_report --days 7 --skip-email
ls out/
```
