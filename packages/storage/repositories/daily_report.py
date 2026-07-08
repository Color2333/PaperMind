"""
每日报告配置数据仓储
@author Color2333
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from packages.storage.models import DailyReportConfig


class DailyReportConfigRepository:
    """每日报告配置仓储"""

    def __init__(self, session: Session):
        self.session = session

    def get_config(self) -> DailyReportConfig:
        """获取每日报告配置（单例）"""
        config = self.session.execute(select(DailyReportConfig)).scalar_one_or_none()

        if not config:
            # 创建默认配置
            config = DailyReportConfig()
            self.session.add(config)
            self.session.flush()

        return config

    def update_config(self, **kwargs) -> DailyReportConfig:
        """更新每日报告配置"""
        config = self.get_config()
        for key, value in kwargs.items():
            if hasattr(config, key):
                setattr(config, key, value)
        return config
