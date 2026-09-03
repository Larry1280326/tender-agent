"""透過 Gmail SMTP 發送電郵（用 Google App Password）。純 stdlib，無額外依賴。"""
from __future__ import annotations

import mimetypes
import smtplib
import time
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

from .. import config

# smtp.gmail.com 會 round-robin 到唔同 IP，部分可能連唔到（尤其經 VPN 嘅「直連」路由）。
# 用多個 hostname 做 fallback，各自重新解析 DNS，盡量踩中可達 IP。
SMTP_HOSTS = ("smtp.googlemail.com", "smtp.gmail.com")
SMTP_PORT = 587
TIMEOUT = 15
ATTEMPTS_PER_HOST = 2
RETRY_DELAY = 1.0
# 假設最慢嘅上傳速度（bytes/秒），用嚟按訊息大小估算 send 所需 timeout。
# 家用慢 uplink ／經代理時，大附件可能要成百秒先傳得晒。
SLOW_UPLINK_BPS = 128 * 1024  # ~128 KB/s


def company_info() -> str:
    """公司資料摘要（公司名／聯絡人／電話／電郵），俾 LLM 喺電郵簽名用；冇設定嘅欄位會跳過。"""
    parts = [f"公司名：{config.COMPANY_NAME}"]
    if config.COMPANY_CONTACT:
        parts.append(f"聯絡人：{config.COMPANY_CONTACT}")
    if config.COMPANY_PHONE:
        parts.append(f"電話：{config.COMPANY_PHONE}")
    if config.COMPANY_EMAIL:
        parts.append(f"電郵：{config.COMPANY_EMAIL}")
    return "，".join(parts)


def send_email(to: str, subject: str, body: str, attachments: list[Path] | None = None) -> str:
    """寄一封電郵。to 可用逗號分隔多個收件人。attachments 為要附加嘅本地檔案路徑。回傳已寄出嘅訊息。"""
    if not config.GMAIL_USER or not config.GMAIL_APP_PASSWORD:
        raise RuntimeError("缺少 GMAIL_USER / GMAIL_APP_PASSWORD（放 backend/.env）")

    msg = EmailMessage()
    msg["From"] = formataddr((config.COMPANY_NAME or config.GMAIL_USER, config.GMAIL_USER))
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    for path in attachments or []:
        ctype, _ = mimetypes.guess_type(path.name)
        maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
        msg.add_attachment(path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name)

    # 大附件上傳可能好慢，send 前按訊息大小加大 socket timeout；
    # connect／handshake 仍用 TIMEOUT，令不可達 host 快啲 fail。
    msg_size = len(msg.as_bytes())
    send_timeout = max(TIMEOUT, msg_size // SLOW_UPLINK_BPS + TIMEOUT)

    last_err: Exception | None = None
    for host in SMTP_HOSTS:
        for attempt in range(1, ATTEMPTS_PER_HOST + 1):
            try:
                with smtplib.SMTP(host, SMTP_PORT, timeout=TIMEOUT) as smtp:
                    smtp.ehlo()
                    smtp.starttls()
                    smtp.ehlo()
                    smtp.login(config.GMAIL_USER, config.GMAIL_APP_PASSWORD)
                    smtp.sock.settimeout(send_timeout)
                    smtp.send_message(msg)
                return f"已發送至 {to}"
            except (OSError, smtplib.SMTPConnectError) as e:
                last_err = e
                if attempt < ATTEMPTS_PER_HOST:
                    time.sleep(RETRY_DELAY)
    raise last_err  # type: ignore[misc]
