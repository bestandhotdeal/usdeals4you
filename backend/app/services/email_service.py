import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


def send_email(to_email: str, subject: str, html: str):
    """
    Gmail SMTP sender (STARTTLS).
    Returns: {"ok": True, "res": {...}} or {"ok": False, "error": "..."}
    """
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")
    from_email = os.getenv("ALERT_FROM_EMAIL", user)

    if not user or not password:
        return {"ok": False, "error": "Missing SMTP_USER/SMTP_PASSWORD in .env"}

    msg = MIMEMultipart("alternative")
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = subject

    part_html = MIMEText(html, "html", "utf-8")
    msg.attach(part_html)

    try:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(user, password)
            server.sendmail(from_email, [to_email], msg.as_string())

        return {"ok": True, "res": {"to": to_email, "subject": subject}}
    except Exception as e:
        return {"ok": False, "error": str(e)}