"""
用户时区工具 - 统一处理面向用户的日期/时间计算
@author Color2333

数据库存储依然用 UTC（_utcnow），但所有"今天是哪天""按日期分组"等
面向用户的逻辑，使用本模块提供的函数，保证与用户本地时间一致。
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from packages.config import get_settings


def _user_tz() -> ZoneInfo:
    """获取用户时区对象"""
    return ZoneInfo(get_settings().user_timezone)


def user_now() -> datetime:
    """当前时刻（带用户时区信息）"""
    return datetime.now(_user_tz())


def user_today_start_utc() -> datetime:
    """用户时区的"今天 0:00"，转为 UTC naive datetime（与数据库 created_at 可比）"""
    tz = _user_tz()
    local_now = datetime.now(tz)
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    # 转成 UTC，再 strip tzinfo 以匹配数据库中的 naive datetime
    utc_midnight = local_midnight.astimezone(timezone.utc).replace(tzinfo=None)
    return utc_midnight


def user_date_str() -> str:
    """用户时区的今日日期字符串，如 '2026-03-01'"""
    return user_now().strftime("%Y-%m-%d")


def utc_offset_hours() -> float:
    """用户时区相对 UTC 的偏移小时数（如东八区返回 8.0）"""
    tz = _user_tz()
    offset = datetime.now(tz).utcoffset()
    if offset is None:
        return 0.0
    return offset.total_seconds() / 3600
