# Tel Aviv Weather Agent

Sends a daily Tel Aviv weather forecast email at 08:00 Israel time, via GitHub Actions.

## Setup

1. Fork or clone this repo as a **private** GitHub repository.
2. Under **Settings → Secrets and variables → Actions**, add two repository secrets:
   - `GMAIL_ADDRESS` — your Gmail address (sender and recipient).
   - `GMAIL_APP_PASSWORD` — a Gmail App Password (requires 2-Step Verification; generate at <https://myaccount.google.com/apppasswords>).
3. Enable workflows under the **Actions** tab if prompted.
4. The workflow runs automatically every day. To test, open **Actions → Daily Tel Aviv Weather Email → Run workflow**.

## Local development

```bash
pip install -r requirements.txt
cp .env.example .env  # fill in real Gmail credentials
python weather_agent.py
```

Weather data comes from [Open-Meteo](https://open-meteo.com/) — no API key required.
