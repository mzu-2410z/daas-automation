# DaaS Pre-Foreclosure Pipeline — Setup & Deployment Guide

> **Audience:** Developer or DevOps engineer deploying this pipeline for a B2B client.  
> **Time to complete:** ~30 minutes.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Project Installation](#2-project-installation)
3. [Create a Google Cloud Service Account](#3-create-a-google-cloud-service-account)
4. [Enable the Google Sheets & Drive APIs](#4-enable-the-google-sheets--drive-apis)
5. [Download the credentials.json File](#5-download-the-credentialsjson-file)
6. [Prepare the Target Google Sheet](#6-prepare-the-target-google-sheet)
7. [Configure the .env File](#7-configure-the-env-file)
8. [Run the Pipeline Locally](#8-run-the-pipeline-locally)
9. [Schedule on a Linux Server (cron)](#9-schedule-on-a-linux-server-cron)
10. [Deploy to a Cloud Environment](#10-deploy-to-a-cloud-environment)
11. [Security Hardening Checklist](#11-security-hardening-checklist)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.10 or later | `python3 --version` to check |
| pip | Latest | `pip install --upgrade pip` |
| Git | Any | Optional but recommended |
| Google Account | — | For creating the Service Account |
| Real Estate API key | — | From your data aggregator (ATTOM, Estated, etc.) |
| Skip Trace API key | — | From your skip trace provider |

---

## 2. Project Installation

```bash
# 1. Clone or copy the project to your server
git clone https://github.com/your-org/daas-pipeline.git
cd daas-pipeline

# 2. Create an isolated virtual environment
python3 -m venv .venv

# 3. Activate the virtual environment
#    Linux / macOS:
source .venv/bin/activate
#    Windows:
.venv\Scripts\activate

# 4. Install all dependencies
pip install -r requirements.txt
```

---

## 3. Create a Google Cloud Service Account

A **Service Account** is a non-human Google identity your pipeline uses to write to Sheets programmatically. It does not require browser-based OAuth.

### Step-by-step

1. Open [https://console.cloud.google.com](https://console.cloud.google.com).
2. In the top navigation bar, click the **project selector** dropdown → **New Project**.
   - Name it something like `daas-pipeline-prod`.
   - Click **Create** and wait for provisioning (~10 seconds).
3. Make sure your new project is selected in the dropdown.
4. In the left sidebar, navigate to **IAM & Admin → Service Accounts**.
5. Click **+ Create Service Account**.
   - **Service account name:** `daas-sheets-writer`
   - **Service account ID:** auto-filled (keep it)
   - **Description:** `DaaS pipeline – writes leads to Google Sheets`
   - Click **Create and Continue**.
6. In the **Grant this service account access to project** step:
   - Role: **Editor** (or the more restrictive **Viewer** + **Sheets API Writer** if you want least-privilege).
   - Click **Continue** → **Done**.

---

## 4. Enable the Google Sheets & Drive APIs

The Service Account needs the APIs activated in your project.

1. In the GCP console, go to **APIs & Services → Library**.
2. Search for **Google Sheets API** → click it → click **Enable**.
3. Go back to the Library. Search for **Google Drive API** → click it → click **Enable**.

> **Why Drive API?** `gspread` uses the Drive API to look up spreadsheet metadata (title, URL). It will fail with a 403 without this.

---

## 5. Download the credentials.json File

1. Navigate to **IAM & Admin → Service Accounts**.
2. Click the `daas-sheets-writer` account you just created.
3. Go to the **Keys** tab.
4. Click **Add Key → Create new key**.
5. Select **JSON** format → **Create**.
6. A file named something like `daas-pipeline-prod-xxxxxxxx.json` will download automatically.
7. **Rename it to `credentials.json`** for clarity.
8. Move it to a secure path **outside your project directory**, e.g.:
   ```
   /home/youruser/secrets/credentials.json   # Linux
   C:\secrets\credentials.json               # Windows
   ```
9. Set strict file permissions (Linux):
   ```bash
   chmod 600 /home/youruser/secrets/credentials.json
   ```

> ⚠️ **Never commit `credentials.json` to Git.** Add `*.json` or the specific path to `.gitignore`.

---

## 6. Prepare the Target Google Sheet

1. Open [https://sheets.google.com](https://sheets.google.com) and create a new spreadsheet (or use an existing one).
2. Name the **tab** (worksheet) at the bottom exactly as you'll set in `GOOGLE_SHEET_TAB_NAME` (default: `Leads`).
3. **Share the sheet with the Service Account email:**
   - Click the **Share** button (top right).
   - In the "Add people and groups" field, paste the service account email.
     - You'll find it in `credentials.json` under the `"client_email"` key, e.g.:
       `daas-sheets-writer@daas-pipeline-prod.iam.gserviceaccount.com`
   - Set permission to **Editor**.
   - **Uncheck "Notify people"** (service accounts don't have inboxes).
   - Click **Share**.
4. Copy the **Sheet ID** from the URL:
   ```
   https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms/edit
                                          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                          This is your GOOGLE_SHEET_ID
   ```

---

## 7. Configure the .env File

```bash
# In the project root
cp .env.example .env
```

Open `.env` in a text editor and fill in every variable:

```dotenv
# Real Estate Data API
REALESTATE_API_BASE_URL=https://api.gateway.realestatedata.com/v1
REALESTATE_API_KEY=sk_live_xxxxxxxxxxxxxxxx

# Skip Trace API
SKIPTRACE_API_BASE_URL=https://api.skiptracegateway.com/v2
SKIPTRACE_API_KEY=st_live_xxxxxxxxxxxxxxxx

# Google
GOOGLE_CREDENTIALS_PATH=/home/youruser/secrets/credentials.json
GOOGLE_SHEET_ID=1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms
GOOGLE_SHEET_TAB_NAME=Leads

# Pipeline config
TARGET_ZIP_CODES=90210,10001,77001
PROPERTIES_PER_ZIP=50

# Rate limiting
REQUEST_DELAY_SECONDS=1.5
MAX_RETRIES=3
RETRY_BACKOFF_FACTOR=2.0

# Logging
LOG_LEVEL=INFO
LOG_FILE=pipeline.log
```

Protect the file:
```bash
chmod 600 .env
```

---

## 8. Run the Pipeline Locally

```bash
# Ensure your virtual environment is active
source .venv/bin/activate

# Execute
python main.py
```

**Expected output (truncated):**
```
2024-09-01 14:00:00 [INFO] main – ============================================================
2024-09-01 14:00:00 [INFO] main – DaaS Pre-Foreclosure Pipeline – START
2024-09-01 14:00:00 [INFO] main – Target ZIP codes : ['90210', '10001']
2024-09-01 14:00:02 [INFO] api_client – Received 48 pre-foreclosure record(s) for ZIP 90210
2024-09-01 14:01:15 [INFO] data_processor – Dropped 7 row(s) with no Phone 1 (41 actionable leads remaining)
2024-09-01 14:01:16 [INFO] gsheet_manager – Appending 41 row(s) starting at cell A2
2024-09-01 14:01:18 [INFO] main – Rows appended to Google Sheet : 41
2024-09-01 14:01:18 [INFO] main – DaaS Pre-Foreclosure Pipeline – COMPLETE
```

---

## 9. Schedule on a Linux Server (cron)

Run the pipeline daily at 7:00 AM server time:

```bash
crontab -e
```

Add this line (adjust paths):
```cron
0 7 * * * /home/youruser/daas-pipeline/.venv/bin/python /home/youruser/daas-pipeline/main.py >> /home/youruser/daas-pipeline/cron.log 2>&1
```

**Tips:**
- Use the **absolute path to the venv Python** to avoid PATH issues in cron.
- The `>> cron.log 2>&1` captures both stdout and stderr into a separate cron log in addition to `pipeline.log`.
- Verify cron is running: `grep CRON /var/log/syslog`

---

## 10. Deploy to a Cloud Environment

### Option A — AWS EC2 / GCP Compute Engine (VM)

1. Provision an `e2-micro` (GCP) or `t3.micro` (AWS) instance with Ubuntu 22.04.
2. SSH in and repeat [Section 2](#2-project-installation).
3. Upload `credentials.json` via SCP:
   ```bash
   scp credentials.json youruser@your-server-ip:/home/youruser/secrets/
   ```
4. Upload `.env` the same way, or use the platform's **Secrets Manager**.
5. Set up cron as in [Section 9](#9-schedule-on-a-linux-server-cron).

### Option B — GitHub Actions (Serverless, Free tier)

Create `.github/workflows/pipeline.yml`:

```yaml
name: DaaS Pipeline

on:
  schedule:
    - cron: "0 7 * * *"   # daily at 07:00 UTC
  workflow_dispatch:       # allow manual trigger

jobs:
  run-pipeline:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Write credentials.json
        run: echo '${{ secrets.GOOGLE_CREDENTIALS_JSON }}' > credentials.json

      - name: Run pipeline
        env:
          REALESTATE_API_KEY:     ${{ secrets.REALESTATE_API_KEY }}
          REALESTATE_API_BASE_URL: ${{ secrets.REALESTATE_API_BASE_URL }}
          SKIPTRACE_API_KEY:      ${{ secrets.SKIPTRACE_API_KEY }}
          SKIPTRACE_API_BASE_URL: ${{ secrets.SKIPTRACE_API_BASE_URL }}
          GOOGLE_CREDENTIALS_PATH: ./credentials.json
          GOOGLE_SHEET_ID:        ${{ secrets.GOOGLE_SHEET_ID }}
          GOOGLE_SHEET_TAB_NAME:  Leads
          TARGET_ZIP_CODES:       ${{ secrets.TARGET_ZIP_CODES }}
          PROPERTIES_PER_ZIP:     "50"
          REQUEST_DELAY_SECONDS:  "1.5"
          MAX_RETRIES:            "3"
          RETRY_BACKOFF_FACTOR:   "2.0"
          LOG_LEVEL:              INFO
          LOG_FILE:               ""
        run: python main.py
```

Add each secret under **Repository Settings → Secrets and variables → Actions**.  
For `GOOGLE_CREDENTIALS_JSON`, paste the entire contents of `credentials.json` as a single-line JSON string.

---

## 11. Security Hardening Checklist

- [ ] `credentials.json` is stored outside the project root and has `chmod 600`.
- [ ] `.env` has `chmod 600`.
- [ ] Both files are listed in `.gitignore`.
- [ ] API keys are rotated on a regular schedule (30–90 days).
- [ ] The Service Account has **only the minimum required permissions** (Editor on the specific sheet, not entire Drive).
- [ ] `LOG_LEVEL` is set to `WARNING` or `ERROR` in production to avoid leaking PII to log files.
- [ ] Log files are rotated (`logrotate` on Linux) to prevent unbounded disk growth.
- [ ] The server running this pipeline has outbound IP whitelisted with your API providers where supported.
- [ ] Dependency versions in `requirements.txt` are pinned (they are – keep them pinned).

---

## 12. Troubleshooting

### `EnvironmentError: Required environment variable '...' is not set`
→ Your `.env` file is missing or the variable is misspelled. Re-check `.env` against `.env.example`.

### `FileNotFoundError: credentials.json not found at '...'`
→ The path in `GOOGLE_CREDENTIALS_PATH` is wrong or the file doesn't exist at that location.

### `SpreadsheetNotFound`
→ Either `GOOGLE_SHEET_ID` is wrong, or the Service Account has not been shared on the spreadsheet. Repeat [Section 6, step 3](#6-prepare-the-target-google-sheet).

### `HTTP 403 – access forbidden` (Google)
→ The Google Sheets API or Drive API is not enabled in your GCP project. Repeat [Section 4](#4-enable-the-google-sheets--drive-apis).

### `HTTP 401 – invalid or missing API key`
→ Check `REALESTATE_API_KEY` / `SKIPTRACE_API_KEY` values in `.env`.

### `RateLimitError`
→ Increase `REQUEST_DELAY_SECONDS` in `.env`. Contact your API provider for your rate limit tier.

### `Clean DataFrame is empty after filtering`
→ All returned leads failed skip-trace enrichment (no Phone 1). This can mean:
  - The skip trace API is down.
  - The properties in the ZIP codes have no traceable owners.
  - Your skip trace API key is invalid.
  
Check `pipeline.log` for per-record `[api_client] Skip trace failed` warnings.
