"""
ChannelRegistry - 渠道动态注册与管理
支持通过装饰器自动注册渠道，动态发现和实例化

使用示例:
```python
from packages.integrations.registry import ChannelRegistry, register_channel

@register_channel("arxiv")
class ArxivChannel(ChannelBase):
    ...

# 动态获取
channel = ChannelRegistry.get("arxiv")
channels = ChannelRegistry.list_channels()
```

@author Color2333
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from packages.integrations.channel_base import ChannelBase

logger = logging.getLogger(__name__)

ChannelFactory = Callable[[], ChannelBase]


class ChannelRegistry:
    """
    渠道注册表

    提供渠道的动态注册、发现和实例化功能。

    使用装饰器注册:
    ```python
    @ChannelRegistry.register("arxiv")
    class ArxivChannel(ChannelBase):
        ...
    ```

    动态获取实例:
    ```python
    channel = ChannelRegistry.get("arxiv")
    ```
    """

    _channels: dict[str, type[ChannelBase]] = {}

    @classmethod
    def register(cls, name: str) -> Callable:
        """
        渠道注册装饰器

        Args:
            name: 渠道名称（如 "arxiv", "ieee", "openalex"）

        使用示例:
        ```python
        @ChannelRegistry.register("arxiv")
        class ArxivChannel(ChannelBase):
            ...
        ```
        """

        def decorator(channel_cls: type[ChannelBase]) -> type[ChannelBase]:
            if name in cls._channels:
                logger.warning("Channel '%s' already registered, overwriting", name)
            cls._channels[name] = channel_cls
            logger.info("Registered channel: %s -> %s", name, channel_cls.__name__)
            return channel_cls

        return decorator

    @classmethod
    def get(cls, name: str, **kwargs) -> ChannelBase | None:
        """
        获取渠道实例

        Args:
            name: 渠道名称
            **kwargs: 传递给渠道构造函数的额外参数

        Returns:
            ChannelBase 实例，如果渠道不存在返回 None
        """
        if name not in cls._channels:
            logger.warning("Channel '%s' not found in registry", name)
            return None

        channel_cls = cls._channels[name]
        try:
            return channel_cls(**kwargs)
        except Exception as exc:
            logger.error("Failed to instantiate channel '%s': %s", name, exc)
            return None

    @classmethod
    def list_channels(cls) -> list[str]:
        """
        列出所有已注册的渠道名称

        Returns:
            渠道名称列表
        """
        return list(cls._channels.keys())

    @classmethod
    def get_channel_info(cls, name: str) -> dict | None:
        """
        获取渠道信息

        Args:
            name: 渠道名称

        Returns:
            渠道信息字典，包含 name, cls, docstring
        """
        if name not in cls._channels:
            return None

        channel_cls = cls._channels[name]
        return {
            "name": name,
            "class": channel_cls.__name__,
            "docstring": channel_cls.__doc__,
        }

    @classmethod
    def register_default_channels(cls) -> None:
        """注册 PaperMind 的默认渠道"""
        from packages.integrations.arxiv_channel import ArxivChannel
        from packages.integrations.biorxiv_channel import BiorxivChannel
        from packages.integrations.dblp_channel import DblpChannel
        from packages.integrations.ieee_channel import IeeeChannel
        from packages.integrations.openalex_search_channel import OpenAlexSearchChannel
        from packages.integrations.semantic_scholar_search_channel import (
            SemanticScholarSearchChannel,
        )

        cls.register("arxiv")(ArxivChannel)
        cls.register("ieee")(IeeeChannel)
        cls.register("openalex")(OpenAlexSearchChannel)
        cls.register("semantic_scholar")(SemanticScholarSearchChannel)
        cls.register("dblp")(DblpChannel)
        cls.register("biorxiv")(BiorxivChannel)

        logger.info("Default channels registered: %s", cls.list_channels())


register_channel = ChannelRegistry.register
