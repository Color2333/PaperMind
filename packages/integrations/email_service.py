"""
邮箱发送服务 - 支持每日简报邮件发送
@author Color2333
"""
from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate
from typing import Literal

from packages.storage.models import EmailConfig

logger = logging.getLogger(__name__)


class EmailService:
    """邮箱发送服务"""

    def __init__(self, config: EmailConfig):
        self.config = config
        self.smtp_server = config.smtp_server
        self.smtp_port = config.smtp_port
        self.smtp_use_tls = config.smtp_use_tls
        self.sender_email = config.sender_email
        self.sender_name = config.sender_name
        self.username = config.username
        self.password = config.password

    def send_email(
        self,
        to_emails: list[str],
        subject: str,
        html_content: str,
        text_content: str | None = None,
    ) -> bool:
        """
        发送邮件

        Args:
            to_emails: 收件人邮箱列表
            subject: 邮件主题
            html_content: HTML 格式邮件内容
            text_content: 纯文本格式邮件内容（可选）

        Returns:
            是否发送成功
        """
        try:
            # 创建邮件对象
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = formataddr((self.sender_name, self.sender_email))
            msg["To"] = ", ".join(to_emails)
            msg["Date"] = formatdate(localtime=True)

            # 添加纯文本内容（可选）
            if text_content:
                msg.attach(MIMEText(text_content, "plain", "utf-8"))

            # 添加 HTML 内容
            msg.attach(MIMEText(html_content, "html", "utf-8"))

            # 连接 SMTP 服务器并发送
            if self.smtp_use_tls:
                server = smtplib.SMTP(self.smtp_server, self.smtp_port)
                server.starttls()
            else:
                server = smtplib.SMTP(self.smtp_server, self.smtp_port)

            server.login(self.username, self.password)
            server.send_message(msg)
            server.quit()

            logger.info(f"邮件发送成功: {subject} -> {to_emails}")
            return True

        except Exception as e:
            logger.error(f"邮件发送失败: {e}", exc_info=True)
            return False

    def send_daily_report(
        self,
        to_emails: list[str],
        report_html: str,
        report_date: str,
    ) -> bool:
        """
        发送每日简报邮件

        Args:
            to_emails: 收件人邮箱列表
            report_html: 简报 HTML 内容
            report_date: 报告日期

        Returns:
            是否发送成功
        """
        subject = f"📚 PaperMind 每日简报 - {report_date}"
        return self.send_email(to_emails, subject, report_html)


def create_test_email(config: EmailConfig) -> bool:
    """
    发送测试邮件

    Args:
        config: 邮箱配置

    Returns:
        是否发送成功
    """
    service = EmailService(config)

    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
            .container { max-width: 600px; margin: 0 auto; padding: 20px; }
            .header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; border-radius: 10px; text-align: center; }
            .content { background: #f7f9fc; padding: 20px; border-radius: 10px; margin-top: 20px; }
            .footer { text-align: center; color: #888; font-size: 12px; margin-top: 20px; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>✅ 邮箱配置测试成功！</h1>
                <p>PaperMind 每日简报功能已就绪</p>
            </div>
            <div class="content">
                <p>恭喜！您的邮箱配置已成功设置。</p>
                <p>从现在起，您将收到每日自动生成的论文研究简报，包括：</p>
                <ul>
                    <li>📄 新搜集的论文列表</li>
                    <li>🔍 自动精读的关键论文</li>
                    <li>📊 研究趋势分析</li>
                    <li>🎯 个性化推荐</li>
                </ul>
                <p>祝您研究顺利！</p>
            </div>
            <div class="footer">
                <p>Powered by PaperMind - 让 AI 帮你读论文</p>
            </div>
        </div>
    </body>
    </html>
    """

    return service.send_email(
        to_emails=[config.sender_email],
        subject="📧 PaperMind 邮箱配置测试",
        html_content=html_content,
    )


def get_default_smtp_config(provider: Literal["gmail", "qq", "163", "outlook"]) -> dict:
    """
    获取常见邮箱服务商的 SMTP 配置

    Args:
        provider: 邮箱服务商

    Returns:
        SMTP 配置字典
    """
    configs = {
        "gmail": {
            "smtp_server": "smtp.gmail.com",
            "smtp_port": 587,
            "smtp_use_tls": True,
        },
        "qq": {
            "smtp_server": "smtp.qq.com",
            "smtp_port": 587,
            "smtp_use_tls": True,
        },
        "163": {
            "smtp_server": "smtp.163.com",
            "smtp_port": 465,
            "smtp_use_tls": True,
        },
        "outlook": {
            "smtp_server": "smtp-mail.outlook.com",
            "smtp_port": 587,
            "smtp_use_tls": True,
        },
    }
    return configs.get(provider, {})
