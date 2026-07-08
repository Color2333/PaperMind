"""
邮箱配置数据仓储
@author Color2333
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from packages.storage.models import EmailConfig


class EmailConfigRepository:
    """邮箱配置仓储"""

    def __init__(self, session: Session):
        self.session = session

    def list_all(self) -> list[EmailConfig]:
        """获取所有邮箱配置"""
        q = select(EmailConfig).order_by(EmailConfig.created_at.desc())
        return list(self.session.execute(q).scalars())

    def get_active(self) -> EmailConfig | None:
        """获取激活的邮箱配置"""
        q = select(EmailConfig).where(EmailConfig.is_active.is_(True))
        return self.session.execute(q).scalar_one_or_none()

    def get_by_id(self, config_id: str) -> EmailConfig | None:
        """根据 ID 获取配置"""
        return self.session.get(EmailConfig, config_id)

    def create(
        self,
        name: str,
        smtp_server: str,
        smtp_port: int,
        smtp_use_tls: bool,
        sender_email: str,
        sender_name: str,
        username: str,
        password: str,
    ) -> EmailConfig:
        """创建邮箱配置"""
        config = EmailConfig(
            name=name,
            smtp_server=smtp_server,
            smtp_port=smtp_port,
            smtp_use_tls=smtp_use_tls,
            sender_email=sender_email,
            sender_name=sender_name,
            username=username,
            password=password,
        )
        self.session.add(config)
        self.session.flush()
        return config

    def update(self, config_id: str, **kwargs) -> EmailConfig | None:
        """更新邮箱配置"""
        config = self.get_by_id(config_id)
        if config:
            for key, value in kwargs.items():
                if hasattr(config, key):
                    setattr(config, key, value)
            self.session.flush()
        return config

    def delete(self, config_id: str) -> bool:
        """删除邮箱配置"""
        config = self.get_by_id(config_id)
        if config:
            self.session.delete(config)
            self.session.flush()
            return True
        return False

    def set_active(self, config_id: str) -> EmailConfig | None:
        """激活指定配置，取消其他配置的激活状态"""
        all_configs = self.list_all()
        for cfg in all_configs:
            cfg.is_active = False
        config = self.get_by_id(config_id)
        if config:
            config.is_active = True
            self.session.flush()
        return config
