"""
Notifications: email (firehose) + Telegram (high-relevance only).

Email is sectioned:
  ★ STRONG MATCHES        (score ≥ threshold)
  🟢 OTHER MATCHES        (in scope, below threshold)

Telegram sends one message per high-match job, capped per run.
"""

import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, List

import requests


# ── Email ───────────────────────────────────────────────────────────────────

def _score_badge(score: float) -> str:
    """A small visual indicator for relevance — coloured pill in HTML."""
    if score >= 0.65:
        return ('<span style="background:#0d6e56;color:#fff;padding:2px 8px;'
                'border-radius:99px;font-size:11px;font-weight:600;">'
                f'★ {score:.2f}</span>')
    if score >= 0.55:
        return ('<span style="background:#185FA5;color:#fff;padding:2px 8px;'
                'border-radius:99px;font-size:11px;font-weight:600;">'
                f'{score:.2f}</span>')
    return ('<span style="background:#e8e8e8;color:#666;padding:2px 8px;'
            'border-radius:99px;font-size:11px;">'
            f'{score:.2f}</span>')


def _source_badge(source: str) -> str:
    is_direct = source not in ("LinkedIn",)
    color = "#0d6e56" if is_direct else "#185FA5"
    label = f"🏢 {source}" if is_direct else "🔗 LinkedIn"
    return (f'<span style="background:{color}18;color:{color};padding:2px 8px;'
            f'border-radius:99px;font-size:11px;font-weight:600;">{label}</span>')


def _job_row_html(job: Dict) -> str:
    score = job.get("score", 0.0)
    scope = job.get("scope", "")
    scope_label = {
        "ireland": "🇮🇪 Ireland",
        "eu_remote": "🇪🇺 EU Remote",
        "remote": "🌍 Remote",
        "visa": "✈️ Visa-sponsor",
    }.get(scope, "")

    return f"""
<tr>
  <td style="padding:14px 18px; border-bottom:1px solid #f0f0f0;">
    <a href="{job['link']}" style="font-size:15px;font-weight:600;
       color:#0a66c2;text-decoration:none;">{job['title']}</a>
    <div style="font-size:13px;color:#444;margin-top:4px;">
      🏢 {job['company']} &nbsp;·&nbsp; 📍 {job['location']}
    </div>
    <div style="margin-top:6px;">
      {_score_badge(score)} &nbsp;
      {_source_badge(job['source'])} &nbsp;
      <span style="font-size:11px;color:#777;">{scope_label}</span>
      <span style="font-size:11px;color:#aaa;margin-left:8px;">🕐 {job['posted']}</span>
    </div>
  </td>
</tr>"""


def _section_html(label: str, jobs: List[Dict], colour: str) -> str:
    if not jobs:
        return ""
    rows = "".join(_job_row_html(j) for j in jobs)
    return f"""
<tr>
  <td style="padding:14px 18px 6px;background:#fafafa;font-size:11px;
             font-weight:700;color:{colour};text-transform:uppercase;
             letter-spacing:0.08em;">
    {label} ({len(jobs)})
  </td>
</tr>{rows}"""


def build_email_html(strong: List[Dict], rest: List[Dict]) -> str:
    date_str = datetime.now().strftime("%a %d %b %Y, %H:%M")
    total = len(strong) + len(rest)

    body = (
        _section_html("★ Strong matches — apply now", strong, "#0d6e56") +
        _section_html("Other in-scope jobs", rest, "#185FA5")
    )

    return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f7f7f8;
                   font-family:'Segoe UI',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0">
<tr><td align="center" style="padding:32px 16px;">
<table width="660" cellpadding="0" cellspacing="0"
       style="background:#fff;border-radius:14px;
              box-shadow:0 2px 16px rgba(0,0,0,.07);overflow:hidden;">
  <tr>
    <td style="background:linear-gradient(135deg,#0a66c2,#0d4f9e);
                padding:26px 30px;color:#fff;">
      <div style="font-size:20px;font-weight:700;">🇮🇪 Job Tracker v5</div>
      <div style="font-size:13px;opacity:.85;margin-top:4px;">
        {total} new job{"s" if total != 1 else ""} &nbsp;·&nbsp;
        {len(strong)} strong match{"es" if len(strong) != 1 else ""} &nbsp;·&nbsp;
        {date_str}
      </div>
    </td>
  </tr>
  <tr><td><table width="100%" cellpadding="0" cellspacing="0">{body}</table></td></tr>
  <tr>
    <td style="padding:18px 30px;background:#fafafa;border-top:1px solid #eee;
               font-size:11px;color:#999;">
      Strong matches (★) also sent to Telegram. Direct ATS listings appear
      before LinkedIn — apply first!
    </td>
  </tr>
</table>
</td></tr></table>
</body></html>"""


def send_email(strong: List[Dict], rest: List[Dict]) -> None:
    sender    = os.environ["EMAIL_SENDER"]
    password  = os.environ["EMAIL_PASSWORD"]
    recipient = os.environ["EMAIL_RECIPIENT"]

    total = len(strong) + len(rest)
    if total == 0:
        return

    subject = (
        f"🇮🇪 {total} new job{'s' if total != 1 else ''} "
        f"({len(strong)} strong) — Job Tracker"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"Job Tracker <{sender}>"
    msg["To"]      = recipient
    msg.attach(MIMEText(build_email_html(strong, rest), "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(sender, password)
        smtp.sendmail(sender, recipient, msg.as_string())

    print(f"  ✉️  Email sent: {total} jobs ({len(strong)} strong)")


# ── Telegram ────────────────────────────────────────────────────────────────

def send_telegram(jobs: List[Dict], max_per_run: int = 5) -> None:
    """
    One message per job, Markdown-formatted. Caps at max_per_run to avoid
    spamming yourself during a high-volume hour. The rest still arrive by email.
    """
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        print("  ⏭  Telegram skipped (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set)")
        return

    if not jobs:
        return

    api_url = f"https://api.telegram.org/bot{token}/sendMessage"
    sent = 0

    for job in jobs[:max_per_run]:
        score = job.get("score", 0)
        scope = job.get("scope", "")
        scope_emoji = {
            "ireland": "🇮🇪",
            "eu_remote": "🇪🇺",
            "remote": "🌍",
            "visa": "✈️",
        }.get(scope, "")

        # Telegram MarkdownV2 needs heavy escaping; use plain HTML mode instead.
        text = (
            f"⭐ <b>{_html_escape(job['title'])}</b>\n"
            f"🏢 {_html_escape(job['company'])}\n"
            f"📍 {_html_escape(job['location'])} {scope_emoji}\n"
            f"🎯 Match score: <b>{score:.2f}</b>  "
            f"·  📡 {_html_escape(job['source'])}\n\n"
            f'<a href="{_html_escape(job["link"])}">→ Open posting</a>'
        )

        try:
            r = requests.post(
                api_url,
                json={
                    "chat_id":     chat_id,
                    "text":        text,
                    "parse_mode":  "HTML",
                    "disable_web_page_preview": False,
                },
                timeout=10,
            )
            if r.status_code == 200:
                sent += 1
            else:
                print(f"  ⚠️  Telegram error {r.status_code}: {r.text[:200]}")
        except Exception as e:
            print(f"  ⚠️  Telegram exception: {e}")

    if len(jobs) > max_per_run:
        # Send a summary message for the overflow
        overflow = len(jobs) - max_per_run
        try:
            requests.post(
                api_url,
                json={
                    "chat_id": chat_id,
                    "text": f"…plus {overflow} more strong match{'es' if overflow != 1 else ''} in the email digest.",
                    "parse_mode": "HTML",
                },
                timeout=10,
            )
        except Exception:
            pass

    print(f"  📱 Telegram: {sent} message{'s' if sent != 1 else ''} sent")


def _html_escape(s: str) -> str:
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))
