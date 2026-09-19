# 🌨️ Daily Weather Report - Longyearbyen

Automated daily weather report generator for Longyearbyen, Svalbard, Norway using the Open-Meteo API. Sends formatted HTML and plain text email notifications.

## ⏰ Automated Schedule

The GitHub Actions workflow runs every day at:
- **8:00 AM IST (Indian Standard Time)** / **2:30 AM UTC**
- Also supports manual execution via the **Run workflow** button in the Actions tab.

## ⚙️ GitHub Actions Configuration

To enable automated email delivery from GitHub Actions, add the following **Repository Secrets** in GitHub (`Settings` -> `Secrets and variables` -> `Actions`):

| Secret Name | Description | Example |
| :--- | :--- | :--- |
| `SENDER_EMAIL` | Sender's Gmail address | `example@gmail.com` |
| `SENDER_PASSWORD` | Google 16-character App Password | `xxxx xxxx xxxx xxxx` |
| `RECIPIENT_EMAIL` | Recipient's email address | `recipient@gmail.com` |

## 🚀 Local Usage

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Run the script:
   ```bash
   python weather_email.py
   ```
