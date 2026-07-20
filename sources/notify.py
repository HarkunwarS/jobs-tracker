"""
Notifications v6: email (everything, grouped by scope) + Telegram (alerts).

Fixes vs v5:
  - v5's _score_badge had a signature mismatch (called with 2 args, defined
    with 1) plus an undefined-variable reference: EVERY email send crashed,
    which also killed Telegram and the seen-cache save downstream. That is
    the main reason the tracker went quiet.
  - Email is now grouped Ireland-first, with category chips.
  - Each notifier is exception-safe; run.py also persists state BEFORE
    notifying, so a flaky SMTP can never cause duplicate-processing loops.
"""

from __future__ import annotations

import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, List

import requests

SCOPE_META = {
    "ireland":   ("🇮🇪 Ireland", 0),
    "eu_remote": ("🇪🇺 Remote — EU", 1),
    "remote":    ("🌍 Remote — anywhere", 2),
    "visa":      ("✈️ Europe (sponsorship mentioned)", 3),
    "asia":      ("🌏 Asia / UAE (sponsorship mentioned)", 4),
}

CATEGORY_LABELS = {
    "software": "Software", "data_ml": "Data/AI", "cloud_devops": "Cloud/DevOps",
    "product_pm": "Product/PM", "ops_supply": "Ops/Supply Chain",
    "business": "Business/Finance", "qa_support": "QA/Support",
    "security": "Security", "grad_scheme": "Grad Scheme", "other": "Other",
}


def _html_escape(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _score_badge(score: float, boost: float = 0.0) -> str:
    if score >= 0.55:
        bg, fg, star = "#0d6e56", "#fff", "★ "
    elif score >= 0.45:
        bg, fg, star = "#185FA5", "#fff", ""
    else:
        bg, fg, star = "#e8e8e8", "#666", ""
    return (f'<span style="background:{bg};color:{fg};padding:2px 8px;'
            f'border-radius:99px;font-size:11px;font-weight:600;">'
            f'{star}{score:.2f}</span>')


def _chip(text: str, color: str = "#555") -> str:
    return (f'<span style="background:{color}14;color:{color};padding:2px 8px;'
            f'border-radius:99px;font-size:11px;font-weight:600;">{_html_escape(text)}</span>')


def _job_row_html(job: Dict) -> str:
    cat = CATEGORY_LABELS.get(job.get("category", "other"), "Other")
    return f"""
<tr>
  <td style="padding:13px 18px;border-bottom:1px solid #f0f0f0;">
    <a href="{_html_escape(job.get('link', '#'))}" style="font-size:15px;font-weight:600;
       color:#0a66c2;text-decoration:none;">{_html_escape(job.get('title', ''))}</a>
    <div style="font-size:13px;color:#444;margin-top:4px;">
      🏢 {_html_escape(job.get('company', ''))} &nbsp;·&nbsp; 📍 {_html_escape(job.get('location', ''))}
    </div>
    <div style="margin-top:6px;">
      {_score_badge(job.get('score', 0.0), job.get('boost', 0.0))} &nbsp;
      {_chip(cat, '#7a4fbc')} &nbsp;
      {_chip(job.get('source', ''), '#185FA5')}
      <span style="font-size:11px;color:#aaa;margin-left:8px;">🕐 {_html_escape(job.get('posted', ''))}</span>
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


def _group_by_scope(jobs: List[Dict]) -> List[tuple]:
    grouped: Dict[str, List[Dict]] = {}
    for j in jobs:
        grouped.setdefault(j.get("scope", "ireland"), []).append(j)
    ordered = sorted(grouped.items(), key=lambda kv: SCOPE_META.get(kv[0], ("", 9))[1])
    return [(SCOPE_META.get(scope, (scope, 9))[0], js) for scope, js in ordered]


def build_email_html(alerts: List[Dict], rest: List[Dict]) -> str:
    date_str = datetime.now().strftime("%a %d %b %Y, %H:%M")
    total = len(alerts) + len(rest)

    body = _section_html("★ Strong matches — apply today", alerts, "#0d6e56")
    for label, jobs in _group_by_scope(rest):
        body += _section_html(label, jobs, "#185FA5")

    return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f7f7f8;
                   font-family:'Segoe UI',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0">
<tr><td align="center" style="padding:32px 16px;">
<table width="680" cellpadding="0" cellspacing="0"
       style="background:#fff;border-radius:14px;
              box-shadow:0 2px 16px rgba(0,0,0,.07);overflow:hidden;">
  <tr>
    <td style="background:linear-gradient(135deg,#0a66c2,#0d4f9e);
                padding:24px 30px;color:#fff;">
      <div style="font-size:20px;font-weight:700;">🇮🇪 Job Tracker v6</div>
      <div style="font-size:13px;opacity:.85;margin-top:4px;">
        {total} new job{"s" if total != 1 else ""} &nbsp;·&nbsp;
        {len(alerts)} strong match{"es" if len(alerts) != 1 else ""} &nbsp;·&nbsp;
        {date_str}
      </div>
    </td>
  </tr>
  <tr><td><table width="100%" cellpadding="0" cellspacing="0">{body}</table></td></tr>
  <tr>
    <td style="padding:16px 30px;background:#fafafa;border-top:1px solid #eee;
               font-size:11px;color:#999;">
      Strong matches (★) also go to Telegram. Direct company listings beat
      LinkedIn reposts — apply to those first.
    </td>
  </tr>
</table>
</td></tr></table>
</body></html>"""


def send_email(alerts: List[Dict], rest: List[Dict]) -> bool:
    sender = os.environ.get("EMAIL_SENDER", "")
    password = os.environ.get("EMAIL_PASSWORD", "")
    recipient = os.environ.get("EMAIL_RECIPIENT", "")
    if not sender or not password or not recipient:
        print("  ⏭  Email skipped (EMAIL_SENDER / EMAIL_PASSWORD / EMAIL_RECIPIENT not all set)")
        return False

    total = len(alerts) + len(rest)
    if total == 0:
        return True

    ireland_n = sum(1 for j in alerts + rest if j.get("scope") == "ireland")
    subject = (f"🇮🇪 {total} new job{'s' if total != 1 else ''} "
               f"({len(alerts)} strong, {ireland_n} Ireland) — Job Tracker")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Job Tracker <{sender}>"
    msg["To"] = recipient
    msg.attach(MIMEText(build_email_html(alerts, rest), "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(sender, password)
            smtp.sendmail(sender, recipient, msg.as_string())
        print(f"  ✉️  Email sent: {total} jobs ({len(alerts)} strong)")
        return True
    except Exception as e:
        print(f"  ⚠️  Email failed: {e}")
        return False


def send_telegram(jobs: List[Dict], max_per_run: int = 10) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("  ⏭  Telegram skipped (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set)")
        return False
    if not jobs:
        return True

    api_url = f"https://api.telegram.org/bot{token}/sendMessage"
    sent = 0
    for job in jobs[:max_per_run]:
        scope_label = SCOPE_META.get(job.get("scope", ""), ("", 9))[0]
        text = (
            f"⭐ <b>{_html_escape(job.get('title', ''))}</b>\n"
            f"🏢 {_html_escape(job.get('company', ''))}\n"
            f"📍 {_html_escape(job.get('location', ''))}  {scope_label}\n"
            f"🎯 Score <b>{job.get('score', 0):.2f}</b> · "
            f"{_html_escape(CATEGORY_LABELS.get(job.get('category', 'other'), 'Other'))} · "
            f"{_html_escape(job.get('source', ''))}\n\n"
            f'<a href="{_html_escape(job.get("link", ""))}">→ Open posting</a>'
        )
        try:
            r = requests.post(api_url, json={
                "chat_id": chat_id, "text": text, "parse_mode": "HTML",
                "disable_web_page_preview": False,
            }, timeout=10)
            if r.status_code == 200:
                sent += 1
            else:
                print(f"  ⚠️  Telegram error {r.status_code}: {r.text[:150]}")
        except Exception as e:
            print(f"  ⚠️  Telegram exception: {e}")

    overflow = len(jobs) - max_per_run
    if overflow > 0:
        try:
            requests.post(api_url, json={
                "chat_id": chat_id, "parse_mode": "HTML",
                "text": f"…plus {overflow} more strong match{'es' if overflow != 1 else ''} in the email digest.",
            }, timeout=10)
        except Exception:
            pass

    print(f"  📱 Telegram: {sent} message(s) sent")
    return sent > 0
