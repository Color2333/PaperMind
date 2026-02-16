"""
通知服务 - 邮件发送 + HTML 存储
@author Bamzc
"""
from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from packages.config import get_settings


class NotificationService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def send_email_html(
        self, recipient: str, subject: str, html: str
    ) -> bool:
        smtp = self.settings
        if not smtp.smtp_host or not smtp.smtp_user or not smtp.smtp_password:
            return False

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = smtp.smtp_from or smtp.smtp_user
        msg["To"] = recipient
        msg.attach(MIMEText(html, "html", "utf-8"))

        with smtplib.SMTP(
            smtp.smtp_host, smtp.smtp_port
        ) as server:
            server.starttls()
            server.login(smtp.smtp_user, smtp.smtp_password)
            server.send_message(msg)
        return True

    def save_brief_html(
        self, filename: str, html: str
    ) -> str:
        target = self.settings.brief_output_root / filename
        Path(target).write_text(html, encoding="utf-8")
        return str(target)
