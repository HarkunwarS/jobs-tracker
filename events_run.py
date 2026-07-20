"""
Events digest — weekly email of Cork/Ireland tech & careers events.

Run by .github/workflows/events.yml every Monday morning. Meetup events
come from public iCal feeds (no API key), gradireland events from their
events page.
"""

from __future__ import annotations

import os
import smtplib
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))

from sources.events import collect_events
from sources.notify import _html_escape  # reuse the escaper


def build_events_html(events) -> str:
    rows = ""
    for e in events:
        rows += f"""
<tr><td style="padding:12px 18px;border-bottom:1px solid #f0f0f0;">
  <a href="{_html_escape(e['link'])}" style="font-size:15px;font-weight:600;
     color:#0a66c2;text-decoration:none;">{_html_escape(e['title'])}</a>
  <div style="font-size:13px;color:#444;margin-top:4px;">
    📅 {_html_escape(e['when'])} &nbsp;·&nbsp; 📍 {_html_escape(e['where'])}
    &nbsp;·&nbsp; <span style="color:#888;">{_html_escape(e['source'])}: {_html_escape(e['group'])}</span>
  </div>
</td></tr>"""
    return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f7f7f8;font-family:'Segoe UI',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:32px 16px;">
<table width="680" cellpadding="0" cellspacing="0"
       style="background:#fff;border-radius:14px;box-shadow:0 2px 16px rgba(0,0,0,.07);overflow:hidden;">
  <tr><td style="background:linear-gradient(135deg,#0d6e56,#0a5a46);padding:24px 30px;color:#fff;">
    <div style="font-size:20px;font-weight:700;">🤝 Networking Events — Cork & Ireland</div>
    <div style="font-size:13px;opacity:.85;margin-top:4px;">
      {len(events)} upcoming event{"s" if len(events) != 1 else ""} · week of {datetime.now():%d %b %Y}
    </div>
  </td></tr>
  <tr><td><table width="100%" cellpadding="0" cellspacing="0">{rows}</table></td></tr>
  <tr><td style="padding:16px 30px;background:#fafafa;border-top:1px solid #eee;font-size:11px;color:#999;">
    Show up, talk to people, mention you're finishing an MSc at UCC and looking
    for graduate roles — referrals beat cold applications.
  </td></tr>
</table></td></tr></table></body></html>"""


def main() -> int:
    print(f"\n🤝 Events digest — {datetime.now():%Y-%m-%d %H:%M}")
    with open("config.yaml") as f:
        cfg = yaml.safe_load(f) or {}

    events = collect_events(cfg)
    print(f"  {len(events)} events collected")
    if not events:
        print("  Nothing upcoming. Done.")
        return 0

    sender = os.environ.get("EMAIL_SENDER", "")
    password = os.environ.get("EMAIL_PASSWORD", "")
    recipient = os.environ.get("EMAIL_RECIPIENT", "")
    if not (sender and password and recipient):
        print("  ⏭  Email secrets not set — printing instead")
        for e in events:
            print(f"   · {e['when']:<22} {e['title']}  ({e['link']})")
        return 0

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🤝 {len(events)} tech & careers events — Cork/Ireland"
    msg["From"] = f"Job Tracker <{sender}>"
    msg["To"] = recipient
    msg.attach(MIMEText(build_events_html(events), "html"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(sender, password)
            smtp.sendmail(sender, recipient, msg.as_string())
        print("  ✉️  Events digest sent")
    except Exception as e:
        print(f"  ⚠️  Email failed: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
