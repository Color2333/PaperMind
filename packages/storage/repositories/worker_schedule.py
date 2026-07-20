"""
Worker 调度配置数据仓储
@author Color2333
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.orm import Session

from packages.storage.models import WorkerScheduleConfig


class WorkerScheduleConfigRepository:
    """Worker 调度配置仓储（单例）"""

    def __init__(self, session: Session):
        self.session = session

    def get_config(self) -> WorkerScheduleConfig:
        """获取 worker 调度配置（单例，不存在则创建默认行）"""
        config = self.session.execute(select(WorkerScheduleConfig)).scalar_one_or_none()

        if not config:
            config = WorkerScheduleConfig()
            self.session.add(config)
            self.session.flush()

        return config

    def update_config(self, **kwargs) -> WorkerScheduleConfig:
        """更新 worker 调度配置"""
        config = self.get_config()
        for key, value in kwargs.items():
            if hasattr(config, key):
                setattr(config, key, value)
        return config

    def update_last_applied_at(self, ts: datetime) -> WorkerScheduleConfig:
        """worker 热重载成功后写回最后应用时间（前端读以显示"已生效"）"""
        config = self.get_config()
        config.last_applied_at = ts
        return config
