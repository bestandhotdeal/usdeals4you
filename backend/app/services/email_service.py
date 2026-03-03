import os
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


def send_email(to_email: str, subject: str, html: str):
    """
    Prefer Resend (HTTPS) if RESEND_API_KEY is set.
    Fallback to SMTP (local dev only).

    Returns:
      {"ok": True, "res": {...}}
      {"ok": False, "error": "..."}
    """
    resend_key = os.getenv("RESEND_API_KEY")
    from_email = os.getenv("ALERT_FROM_EMAIL") or "onboarding@resend.dev"

    # A) Resend over HTTPS
    if resend_key:
        try:
            r = requests.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {resend_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": from_email,
                    "to": [to_email],
                    "subject": subject,
                    "html": html,
                },
                timeout=30,
            )
            if 200 <= r.status_code < 300:
                data = r.json() if r.text else {}
                return {"ok": True, "res": {"provider": "resend", "id": data.get("id"), "to": to_email}}
            return {"ok": False, "error": f"Resend HTTP {r.status_code}: {r.text[:400]}"}
        except Exception as e:
            return {"ok": False, "error": f"Resend error: {e}"}

    # B) SMTP fallback (local only)
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")
    smtp_from = os.getenv("ALERT_FROM_EMAIL") or user

    if not user or not password:
        return {"ok": False, "error": "Missing SMTP_USER/SMTP_PASSWORD in env"}

    msg = MIMEMultipart("alternative")
    msg["From"] = smtp_from
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(user, password)
            server.sendmail(smtp_from, [to_email], msg.as_string())
        return {"ok": True, "res": {"provider": "smtp", "to": to_email, "subject": subject}}
    except Exception as e:
        return {"ok": False, "error": str(e)}
