"""
Context Compaction — 3层压缩策略，支持无限长度会话

@author Color2333
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from packages.integrations.llm_client import LLMClient

logger = logging.getLogger(__name__)


class CompactionLevel(Enum):
    """压缩层级"""

    NONE = "none"
    LAYER1_SUMMARIZE = "layer1"  # 消息摘要
    LAYER2_KEY_DECISIONS = "layer2"  # 关键决策提取
    LAYER3_METADATA = "layer3"  # 元信息压缩


@dataclass
class CompactionConfig:
    """压缩配置"""

    threshold_ratio: float = 0.5  # 触发压缩的 token 占比阈值
    max_tool_calls_per_round: int = 20  # 单轮最大工具调用次数
    max_session_duration_hours: float = 2.0  # 最大会话时长（小时）
    max_messages_count: int = 20  # 最大消息数量（超过则使用 Layer 3）


@dataclass
class CompactionResult:
    """压缩结果"""

    compressed_messages: list[dict[str, Any]]
    level: CompactionLevel
    original_token_count: int
    compressed_token_count: int
    compression_ratio: float = 0.0


@dataclass
class SessionMetadata:
    """会话元信息"""

    summary: str = ""
    decisions: list[str] = field(default_factory=list)
    files_touched: list[str] = field(default_factory=list)
    active_task: str = ""
    next_step: str = ""
    tool_calls_count: int = 0


class ContextCompactor:
    """
    3层 Context 压缩策略

    Layer 1: 消息摘要（定期把多轮对话压缩成一条摘要消息）
    Layer 2: 关键决策提取（只保留重要的架构决策、操作结果、文件路径）
    Layer 3: 元信息压缩（把完整消息压缩成结构化元信息）
    """

    def __init__(
        self,
        llm: LLMClient,
        max_tokens: int = 8192,
        config: CompactionConfig | None = None,
    ):
        self.llm = llm
        self.max_tokens = max_tokens
        self.config = config or CompactionConfig()
        self._session_start_time = time.time()

    def should_compact(self, messages: list[dict[str, Any]]) -> CompactionLevel:
        """检查是否需要压缩，返回需要的压缩层级"""
        if not messages:
            return CompactionLevel.NONE

        total_tokens = self._estimate_tokens(messages)
        threshold_tokens = int(self.max_tokens * self.config.threshold_ratio)

        # Layer 3: 历史消息全部是工具调用
        if len(messages) > 5 and self._is_all_tool_messages(messages):
            logger.info("触发 Layer 3 压缩：历史消息全部是工具调用")
            return CompactionLevel.LAYER3_METADATA

        # Layer 2: 单轮工具调用过多 或 会话超时
        recent_tool_calls = self._count_recent_tool_calls(messages)
        session_duration = (time.time() - self._session_start_time) / 3600

        if recent_tool_calls > self.config.max_tool_calls_per_round:
            logger.info(
                "触发 Layer 2 压缩：单轮工具调用 %d 次",
                recent_tool_calls,
            )
            return CompactionLevel.LAYER2_KEY_DECISIONS

        if session_duration > self.config.max_session_duration_hours:
            logger.info(
                "触发 Layer 2 压缩：会话时长 %.1f 小时",
                session_duration,
            )
            return CompactionLevel.LAYER2_KEY_DECISIONS

        # Layer 1: 消息总长度超过阈值
        if total_tokens > threshold_tokens:
            logger.info(
                "触发 Layer 1 压缩：token %d > 阈值 %d",
                total_tokens,
                threshold_tokens,
            )
            return CompactionLevel.LAYER1_SUMMARIZE

        return CompactionLevel.NONE

    def compact(
        self,
        messages: list[dict[str, Any]],
        level: CompactionLevel | None = None,
    ) -> CompactionResult:
        """执行压缩"""
        if level is None:
            level = self.should_compact(messages)

        if level == CompactionLevel.NONE:
            return CompactionResult(
                compressed_messages=messages,
                level=CompactionLevel.NONE,
                original_token_count=self._estimate_tokens(messages),
                compressed_token_count=self._estimate_tokens(messages),
            )

        # 自动选择压缩策略
        if level == CompactionLevel.LAYER1_SUMMARIZE:
            compressed = self.layer1_summarize(messages)
        elif level == CompactionLevel.LAYER2_KEY_DECISIONS:
            compressed = self.layer2_key_decisions(messages)
        elif level == CompactionLevel.LAYER3_METADATA:
            compressed = self.layer3_metadata(messages)
        else:
            compressed = messages

        original_tokens = self._estimate_tokens(messages)
        compressed_tokens = self._estimate_tokens(compressed)
        ratio = (
            (original_tokens - compressed_tokens) / original_tokens if original_tokens > 0 else 0.0
        )

        logger.info(
            "Context 压缩完成：%.1f%% (%d -> %d tokens)",
            ratio * 100,
            original_tokens,
            compressed_tokens,
        )

        return CompactionResult(
            compressed_messages=compressed,
            level=level,
            original_token_count=original_tokens,
            compressed_token_count=compressed_tokens,
            compression_ratio=ratio,
        )

    def layer1_summarize(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Layer 1: 消息摘要
        把多轮对话压缩成一条摘要消息
        """
        if len(messages) < 3:
            return messages

        # 构建对话历史文本
        history_text = self._build_history_text(messages)

        prompt = f"""请将以下对话历史压缩成简洁的摘要（不超过150字），保留关键信息：

{history_text}

要求：
1. 突出用户的原始需求
2. 保留已完成的操作结果
3. 省略中间探索过程
4. 使用简洁的自然语言"""

        try:
            result = self.llm.summarize_text(prompt, stage="compaction", max_tokens=300)
            summary = result.content.strip()
        except Exception as exc:
            logger.warning("Layer 1 摘要生成失败: %s", exc)
            summary = self._fallback_summarize(messages)

        # 构建压缩后的消息
        compressed = [
            {
                "role": "user",
                "content": f"[对话历史摘要]\n{summary}",
            }
        ]

        # 保留最近的一轮对话（如果有的话）
        if len(messages) >= 2:
            compressed.extend(messages[-2:])

        return compressed

    def layer2_key_decisions(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Layer 2: 关键决策提取
        只保留重要的架构决策、操作结果、文件路径
        """
        history_text = self._build_history_text(messages)

        prompt = f"""请从以下对话历史中提取关键决策和项目状态，输出结构化信息：

{history_text}

请按以下格式输出：

=== 项目状态 ===
- [已完成的主要任务]
- [关键技术决策]

=== 关键文件 ===
- [涉及的重要文件路径]

=== 当前进行中 ===
[正在进行的任务描述]

=== 下一步 ===
[推荐的下一步操作]"""

        try:
            result = self.llm.summarize_text(prompt, stage="compaction", max_tokens=500)
            decisions = result.content.strip()
        except Exception as exc:
            logger.warning("Layer 2 决策提取失败: %s", exc)
            decisions = self._fallback_decisions(messages)

        compressed = [
            {
                "role": "user",
                "content": f"[关键决策与项目状态]\n{decisions}",
            }
        ]

        # 保留最近一轮对话
        if len(messages) >= 2:
            compressed.extend(messages[-2:])

        return compressed

    def layer3_metadata(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Layer 3: 元信息压缩
        把完整消息压缩成结构化元信息
        """
        metadata = self._extract_metadata(messages)

        # 构建结构化消息
        content_parts = [
            "[会话元信息 - 已压缩]",
            f"摘要: {metadata.summary}",
        ]

        if metadata.decisions:
            content_parts.append(f"关键决策: {', '.join(metadata.decisions[:5])}")

        if metadata.files_touched:
            content_parts.append(f"涉及文件: {', '.join(metadata.files_touched[:10])}")

        if metadata.active_task:
            content_parts.append(f"当前任务: {metadata.active_task}")

        if metadata.next_step:
            content_parts.append(f"下一步: {metadata.next_step}")

        content_parts.append(f"工具调用次数: {metadata.tool_calls_count}")

        compressed = [
            {
                "role": "user",
                "content": "\n".join(content_parts),
            }
        ]

        return compressed

    # -- Helper Methods --

    def _estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        """估算消息列表的 token 数量"""
        total_chars = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total_chars += len(content)
            elif isinstance(content, list):
                # 处理多模态内容
                for item in content:
                    if isinstance(item, dict) and "text" in item:
                        total_chars += len(item["text"])
                    elif isinstance(item, str):
                        total_chars += len(item)

            # 工具调用额外计算
            if "tool_calls" in msg:
                for tc in msg["tool_calls"]:
                    fn = tc.get("function", {})
                    total_chars += len(fn.get("name", ""))
                    total_chars += len(fn.get("arguments", ""))

        # 粗略估算：1 token ≈ 4 chars
        return total_chars // 4

    def _count_recent_tool_calls(self, messages: list[dict[str, Any]]) -> int:
        """统计最近一轮的工具调用次数"""
        count = 0
        # 从后往前找最近的 assistant 消息
        for msg in reversed(messages):
            if msg.get("role") == "assistant" and "tool_calls" in msg:
                count = len(msg.get("tool_calls", []))
                break
        return count

    def _is_all_tool_messages(self, messages: list[dict[str, Any]]) -> bool:
        """检查是否所有消息都是工具调用相关"""
        if not messages:
            return False

        for msg in messages[:-2]:  # 排除最近两轮
            role = msg.get("role", "")
            if role == "user":
                content = msg.get("content", "")
                # 如果有普通文本内容（非 tool_result）
                if isinstance(content, str) and content and "tool" not in content.lower():
                    return False
            elif role == "assistant":
                if "tool_calls" not in msg:
                    # 有普通文本回复
                    content = msg.get("content", "")
                    if content and len(content) > 50:
                        return False

        return True

    def _build_history_text(self, messages: list[dict[str, Any]]) -> str:
        """构建对话历史文本"""
        parts = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")

            if isinstance(content, str):
                parts.append(f"[{role}] {content[:500]}")
            elif isinstance(content, list):
                # 处理 tool_result 等
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "tool_result":
                            parts.append(f"[tool_result] {str(item.get('content', ''))[:200]}")
                        elif "text" in item:
                            parts.append(f"[{role}] {item['text'][:500]}")

            # 工具调用信息
            if "tool_calls" in msg:
                for tc in msg.get("tool_calls", []):
                    fn = tc.get("function", {})
                    name = fn.get("name", "unknown")
                    parts.append(f"[tool_call] {name}")

        return "\n".join(parts)

    def _extract_metadata(self, messages: list[dict[str, Any]]) -> SessionMetadata:
        """从消息中提取元信息"""
        metadata = SessionMetadata()
        tool_names = set()

        for msg in messages:
            # 提取工具调用
            if "tool_calls" in msg:
                for tc in msg["tool_calls"]:
                    fn = tc.get("function", {})
                    tool_names.add(fn.get("name", ""))
                    metadata.tool_calls_count += 1

            # 提取文件路径
            content = msg.get("content", "")
            if isinstance(content, str):
                # 简单的文件路径提取（匹配常见模式）
                import re

                paths = re.findall(r"[a-zA-Z0-9_\-./]+\.[a-zA-Z]{1,4}", content)
                metadata.files_touched.extend(paths[:3])

            # 提取决策关键词
            if "decision" in str(content).lower() or "选择" in str(content):
                metadata.decisions.append(str(content)[:100])

        metadata.files_touched = list(set(metadata.files_touched))[:10]

        # 尝试提取当前任务（从最近的用户消息）
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str) and len(content) > 10:
                    metadata.active_task = content[:100]
                    break

        # 生成简单摘要
        if messages:
            metadata.summary = (
                f"处理了 {len(messages)} 条消息，调用了 {metadata.tool_calls_count} 次工具"
            )

        return metadata

    def _fallback_summarize(self, messages: list[dict[str, Any]]) -> str:
        """摘要生成失败时的回退方案"""
        total = len(messages)
        tool_count = sum(1 for m in messages if "tool_calls" in m)
        return f"对话包含 {total} 条消息，其中 {tool_count} 轮涉及工具调用"

    def _fallback_decisions(self, messages: list[dict[str, Any]]) -> str:
        """决策提取失败时的回退方案"""
        tool_names = self._extract_tool_names(messages)
        return f"项目中使用了以下工具: {', '.join(tool_names[:5]) if tool_names else '无'}"

    def _extract_tool_names(self, messages: list[dict[str, Any]]) -> list[str]:
        """提取所有工具调用名称"""
        names = []
        for msg in messages:
            if "tool_calls" in msg:
                for tc in msg["tool_calls"]:
                    fn = tc.get("function", {})
                    name = fn.get("name", "")
                    if name and name not in names:
                        names.append(name)
        return names


class CompactingStreamingAgentLoop:
    """
    混入类：为 StreamingAgentLoop 添加压缩功能

    使用方式：
        class MyAgentLoop(CompactingStreamingAgentLoop, StreamingAgentLoop):
            pass

        # 或者在初始化时混入
        loop = CompactingStreamingAgentLoop(
            llm=llm_client,
            tools=tools,
            ...,
            enable_compaction=True,
        )
    """

    def __init__(
        self,
        *args,
        enable_compaction: bool = True,
        compaction_config: CompactionConfig | None = None,
        **kwargs,
    ):
        # 调用父类初始化
        super().__init__(*args, **kwargs)

        self._enable_compaction = enable_compaction
        self._compaction_config = compaction_config or CompactionConfig()

        # 延迟初始化 compactor（需要 llm 实例）
        self._compactor: ContextCompactor | None = None

    def _get_compactor(self) -> ContextCompactor | None:
        """获取或创建 compactor 实例"""
        if not self._enable_compaction:
            return None

        if self._compactor is None:
            # 从父类获取 llm 和 max_tokens
            llm = getattr(self, "llm", None)
            max_tokens = getattr(self, "max_tokens", 8192)

            if llm is None:
                logger.warning("无法初始化 ContextCompactor: llm 实例不可用")
                return None

            self._compactor = ContextCompactor(
                llm=llm,
                max_tokens=max_tokens,
                config=self._compaction_config,
            )

        return self._compactor

    def run(self, conversation: list[dict[str, Any]]) -> Iterator[str]:
        """执行流式 Agent 循环，并在结束后检查是否需要压缩"""
        # 调用父类的 run 方法
        yield from super().run(conversation)  # type: ignore[misc]

        # 检查并执行压缩
        if self._enable_compaction:
            compactor = self._get_compactor()
            if compactor:
                level = compactor.should_compact(conversation)
                if level != CompactionLevel.NONE:
                    logger.info("执行 Context 压缩: %s", level.value)
                    result = compactor.compact(conversation, level)
                    # 替换原始消息
                    conversation.clear()
                    conversation.extend(result.compressed_messages)
