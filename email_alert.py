"""
Email alert module for sending scan results and trade notifications.

Uses SMTP to send email alerts. Configure your email settings
in Streamlit secrets or environment variables.
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os


def send_email_alert(subject: str, body: str, to_email: str = None):
    """
    Send an email alert with the given subject and body.

    Parameters
    ----------
    subject : str
        Email subject line.
    body : str
        Email body content (plain text).
    to_email : str, optional
        Recipient email address. Falls back to ALERT_EMAIL env var.

    Raises
    ------
    Exception
        If email sending fails or credentials are not configured.
    """
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    sender_email = os.getenv("SENDER_EMAIL", "")
    sender_password = os.getenv("SENDER_PASSWORD", "")
    recipient = to_email or os.getenv("ALERT_EMAIL", "")

    if not sender_email or not sender_password:
        raise Exception(
            "Email not configured. Set SENDER_EMAIL and SENDER_PASSWORD "
            "environment variables or Streamlit secrets."
        )

    if not recipient:
        raise Exception(
            "No recipient email. Pass to_email or set ALERT_EMAIL env var."
        )

    msg = MIMEMultipart()
    msg["From"] = sender_email
    msg["To"] = recipient
    msg["Subject"] = f"🔔 AlgoTrading Alert: {subject}"

    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls()
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, recipient, msg.as_string())

    print(f"✅ Email alert sent to {recipient}")
