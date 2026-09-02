"""透過 Gmail SMTP 發送電郵（用 Google App Password）。純 stdlib，無額外依賴。"""
from __future__ import annotations

import smtplib
import time
from email.message import EmailMessage

from .. import config

# smtp.gmail.com 會 round-robin 到唔同 IP，部分可能連唔到（尤其經 VPN 嘅「直連」路由）。
# 用多個 hostname 做 fallback，各自重新解析 DNS，盡量踩中可達 IP。
SMTP_HOSTS = ("smtp.gmail.com", "smtp.googlemail.com")
SMTP_PORT = 587
TIMEOUT = 15
ATTEMPTS_PER_HOST = 2
RETRY_DELAY = 1.0


def send_email(to: str, subject: str, body: str) -> str:
    """寄一封純文字電郵。to 可用逗號分隔多個收件人。回傳已寄出嘅訊息。"""
    if not config.GMAIL_USER or not config.GMAIL_APP_PASSWORD:
        raise RuntimeError("缺少 GMAIL_USER / GMAIL_APP_PASSWORD（放 backend/.env）")

    msg = EmailMessage()
    msg["From"] = config.GMAIL_USER
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    last_err: Exception | None = None
    for host in SMTP_HOSTS:
        for attempt in range(1, ATTEMPTS_PER_HOST + 1):
            try:
                with smtplib.SMTP(host, SMTP_PORT, timeout=TIMEOUT) as smtp:
                    smtp.ehlo()
                    smtp.starttls()
                    smtp.ehlo()
                    smtp.login(config.GMAIL_USER, config.GMAIL_APP_PASSWORD)
                    smtp.send_message(msg)
                return f"已發送至 {to}"
            except (OSError, smtplib.SMTPConnectError) as e:
                last_err = e
                if attempt < ATTEMPTS_PER_HOST:
                    time.sleep(RETRY_DELAY)
    raise last_err  # type: ignore[misc]
