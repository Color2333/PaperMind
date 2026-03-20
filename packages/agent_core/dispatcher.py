"""
ToolDispatcher — 工具注册与分发，参考 learn-claude-code s02

核心模式（s02）：
    "Adding a tool means adding one handler"
    工具通过 name → handler 注册到 dispatch map
    loop 不变，加工具 = 加 handler

    TOOL_HANDLERS = {
        "bash":       lambda **kw: run_bash(kw["command"]),
        "read_file":  lambda **kw: run_read(kw["path"]),
        "task_create": lambda **kw: TASKS.create(kw["subject"], ...),
    }

关键设计原则：
1. 工具定义（tools list）和工具处理（handlers dict）分离
2. 工具定义用于 LLM 的 tool_use API
3. 工具处理用于实际执行
4. 注册顺序不影响功能
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

from .tools.bash import run_bash
from .tools.filesystem import run_edit, run_glob, run_grep, run_read, run_write


class ToolDispatcher:
    """
    工具注册与分发中心。

    使用方式：
        dispatcher = ToolDispatcher()
        dispatcher.register("bash", run_bash)
        dispatcher.register("read_file", run_read)
        dispatcher.register("task_create", task_manager.create)
        dispatcher.register("task_list", task_manager.list_all)

        # 批量注册
        dispatcher.register_many({
            "bash": run_bash,
            "read_file": run_read,
            "write_file": run_write,
        })
    """

    def __init__(self):
        self._handlers: dict[str, Callable[..., str | dict[str, Any]]] = {}
        self._tool_definitions: list[dict[str, Any]] = []
        self._frozen = False

    def register(
        self,
        name: str,
        handler: Callable[..., str | dict[str, Any]],
        description: str | None = None,
        input_schema: dict[str, Any] | None = None,
    ) -> ToolDispatcher:
        """
        注册一个工具。

        参数：
            name: 工具名称，LLM 通过这个名称调用
            handler: 执行函数，接受 **kwargs
            description: 工具描述（默认从 handler docstring 提取）
            input_schema: Anthropic tool input schema（默认从 handler 签名推断）
        """
        if self._frozen:
            raise RuntimeError(
                "Cannot register tools after get_tool_definitions() was called. Register all tools first."
            )

        self._handlers[name] = handler

        if description is None:
            description = self._extract_description(handler)

        if input_schema is None:
            input_schema = self._infer_schema(handler)

        tool_def = {
            "name": name,
            "description": description,
            "input_schema": input_schema,
        }
        self._tool_definitions.append(tool_def)
        return self

    def register_many(
        self,
        tools: dict[str, Callable[..., str | dict[str, Any]]],
    ) -> ToolDispatcher:
        """批量注册工具"""
        for name, handler in tools.items():
            self.register(name, handler)
        return self

    def dispatch(self, name: str, **kwargs) -> str | dict[str, Any]:
        """
        分发工具调用到对应 handler。
        如果 handler 抛出异常，捕获后返回错误字符串。
        """
        handler = self._handlers.get(name)
        if handler is None:
            return f"Error: Unknown tool '{name}'. Available: {list(self._handlers.keys())}"

        try:
            result = handler(**kwargs)
            return result
        except TypeError as exc:
            # 参数不匹配
            sig = inspect.signature(handler)
            return (
                f"Error: Tool '{name}' received wrong arguments. "
                f"Expected params: {list(sig.parameters.keys())}. Error: {exc}"
            )
        except Exception as exc:  # noqa: BLE001
            return f"Error: Tool '{name}' failed: {type(exc).__name__}: {exc}"

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """
        返回 Anthropic 格式的工具定义列表。
        一旦调用，冻结注册——不能再添加工具。
        """
        self._frozen = True
        return self._tool_definitions

    def list_tools(self) -> list[str]:
        """列出所有已注册工具名称"""
        return list(self._handlers.keys())

    def unregister(self, name: str) -> bool:
        """注销一个工具（谨慎使用）"""
        if name in self._handlers:
            del self._handlers[name]
            self._tool_definitions = [t for t in self._tool_definitions if t["name"] != name]
            self._frozen = False
            return True
        return False

    # -- 私有工具 --
    @staticmethod
    def _extract_description(handler: Callable) -> str:
        doc = inspect.getdoc(handler) or ""
        return doc.split("\n")[0].strip() if doc else f"Tool: {handler.__name__}"

    @staticmethod
    def _infer_schema(handler: Callable) -> dict[str, Any]:
        """
        从 handler 签名推断 input_schema。
        只处理基本类型：str, int, float, bool, list
        """
        sig = inspect.signature(handler)
        properties: dict[str, dict[str, Any]] = {}
        required: list[str] = []

        for param_name, param in sig.parameters.items():
            if param_name in ("self", "kwargs", "args"):
                continue

            annotation = param.annotation
            if annotation is inspect.Parameter.empty:
                param_type = "string"
            else:
                param_type = ToolDispatcher._annotation_to_json_type(annotation)

            prop = {"type": param_type}
            if param.default is not inspect.Parameter.empty:
                prop["default"] = param.default

            properties[param_name] = prop

            if param.default is inspect.Parameter.empty and param_name != "self":
                required.append(param_name)

        return {
            "type": "object",
            "properties": properties,
            "required": required if required else None,
        }

    @staticmethod
    def _annotation_to_json_type(annotation: Any) -> str:
        """将 Python 类型映射到 JSON Schema 类型"""
        origin = getattr(annotation, "__origin__", None)

        if origin is list:
            return "array"
        if origin is dict:
            return "object"

        name = getattr(annotation, "__name__", str(annotation))
        mapping = {
            "str": "string",
            "int": "integer",
            "float": "number",
            "bool": "boolean",
            "list": "array",
            "dict": "object",
        }
        return mapping.get(name, "string")


# -- 全局默认工具注册表 --
def make_default_dispatcher(
    tasks_dir: str | None = None,
    workdir: str | None = None,
) -> ToolDispatcher:
    """
    创建默认工具集的 dispatcher。
    包含所有基础工具：bash, read, write, edit, glob, grep
    可选添加 tasks 工具。
    """
    from pathlib import Path

    workdir_path = Path(workdir) if workdir else Path.cwd()

    def bash(command: str) -> str:
        return run_bash(command, cwd=str(workdir_path))

    dispatcher = ToolDispatcher()
    dispatcher.register("bash", bash)
    dispatcher.register("read_file", run_read)
    dispatcher.register("write_file", run_write)
    dispatcher.register("edit_file", run_edit)
    dispatcher.register("glob", run_glob)
    dispatcher.register("grep", run_grep)

    if tasks_dir:
        from .tasks import TaskManager

        tm = TaskManager(Path(tasks_dir))
        dispatcher.register(
            "task_create", lambda subject, description="": tm.create(subject, description)
        )
        dispatcher.register("task_list", lambda: tm.list_all())
        dispatcher.register("task_get", lambda task_id: tm.get(task_id))
        dispatcher.register(
            "task_update",
            lambda task_id, status=None, owner=None: tm.update(task_id, status, owner),
        )

    return dispatcher


# =============================================================================
# PaperMind 适配层：流式工具分发器
# =============================================================================

logger = logging.getLogger(__name__)


@dataclass
class PaperMindToolResult:
    """PaperMind 风格的工具结果"""

    success: bool
    data: dict = field(default_factory=dict)
    summary: str = ""


@dataclass
class PaperMindToolProgress:
    """PaperMind 风格的工具进度"""

    message: str
    current: int = 0
    total: int = 0


class StreamingToolDispatcher:
    """
    PaperMind 专用的流式工具分发器。

    支持注册生成器式的 handler（返回 Iterator[ToolProgress | ToolResult]），
    同时兼容普通同步 handler。

    使用方式：
        dispatcher = StreamingToolDispatcher()
        dispatcher.register("search_papers", search_papers_handler)  # generator
        dispatcher.register("bash", bash_handler)  # sync

        # 流式执行
        for item in dispatcher.dispatch_stream("search_papers", {"keyword": "AI"}):
            if isinstance(item, PaperMindToolProgress):
                print(f"进度: {item.message}")
            elif isinstance(item, PaperMindToolResult):
                print(f"完成: {item.summary}")
    """

    def __init__(self):
        self._handlers: dict[str, Callable[..., Any]] = {}
        self._tool_definitions: list[dict[str, Any]] = []
        self._frozen = False

    def register(
        self,
        name: str,
        handler: Callable[..., Any],
        description: str | None = None,
        input_schema: dict[str, Any] | None = None,
        requires_confirm: bool = False,
    ) -> StreamingToolDispatcher:
        """
        注册一个工具 handler。

        参数：
            name: 工具名称
            handler: 执行函数，可以是普通函数或生成器函数
            description: 工具描述（默认从 handler docstring 提取）
            input_schema: OpenAI function calling 格式的参数 schema
            requires_confirm: 是否需要用户确认
        """
        if self._frozen:
            raise RuntimeError(
                "Cannot register tools after get_tool_definitions() was called. "
                "Register all tools first."
            )

        self._handlers[name] = handler

        if description is None:
            description = self._extract_description(handler)

        if input_schema is None:
            input_schema = self._infer_schema(handler)

        tool_def = {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": input_schema,
            },
        }
        self._tool_definitions.append(tool_def)
        return self

    def register_many(
        self,
        tools: dict[str, Callable[..., Any]],
    ) -> StreamingToolDispatcher:
        """批量注册工具（不包含 requires_confirm）"""
        for name, handler in tools.items():
            self.register(name, handler)
        return self

    def dispatch_stream(
        self,
        name: str,
        arguments: dict,
    ) -> Iterator[PaperMindToolProgress | PaperMindToolResult]:
        """
        流式执行工具，yield 进度事件和最终结果。
        兼容生成器 handler 和普通 handler。
        """
        handler = self._handlers.get(name)
        if handler is None:
            yield PaperMindToolResult(
                success=False,
                summary=f"未知工具: {name}",
            )
            return

        try:
            result = handler(**arguments)
            if hasattr(result, "__next__"):
                # 生成器函数
                yield from result
            else:
                # 普通同步函数，直接包装为 ToolResult
                if isinstance(result, PaperMindToolResult):
                    yield result
                elif isinstance(result, dict):
                    yield PaperMindToolResult(success=True, data=result, summary="")
                elif isinstance(result, str):
                    yield PaperMindToolResult(success=True, summary=result)
                else:
                    yield PaperMindToolResult(success=True, summary=str(result))
        except Exception as exc:
            logger.exception("Tool %s failed: %s", name, exc)
            yield PaperMindToolResult(success=False, summary=str(exc))

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """
        返回 OpenAI function calling 格式的工具定义列表。
        一旦调用，冻结注册——不能再添加工具。
        """
        self._frozen = True
        return self._tool_definitions

    def list_tools(self) -> list[str]:
        """列出所有已注册工具名称"""
        return list(self._handlers.keys())

    def get_handler(self, name: str) -> Callable[..., Any] | None:
        """获取工具 handler"""
        return self._handlers.get(name)

    def _extract_description(self, handler: Callable) -> str:
        doc = inspect.getdoc(handler) or ""
        return doc.split("\n")[0].strip() if doc else f"Tool: {handler.__name__}"

    def _infer_schema(self, handler: Callable) -> dict[str, Any]:
        """从 handler 签名推断参数 schema"""
        sig = inspect.signature(handler)
        properties: dict[str, dict[str, Any]] = {}
        required: list[str] = []

        for param_name, param in sig.parameters.items():
            if param_name in ("self", "kwargs", "args"):
                continue

            annotation = param.annotation
            if annotation is inspect.Parameter.empty:
                param_type = "string"
            else:
                param_type = self._annotation_to_json_type(annotation)

            prop: dict[str, Any] = {"type": param_type}
            if param.default is not inspect.Parameter.empty:
                prop["default"] = param.default

            properties[param_name] = prop

            if param.default is inspect.Parameter.empty and param_name != "self":
                required.append(param_name)

        return {
            "type": "object",
            "properties": properties,
            "required": required if required else None,
        }

    @staticmethod
    def _annotation_to_json_type(annotation: Any) -> str:
        """将 Python 类型映射到 JSON Schema 类型"""
        origin = getattr(annotation, "__origin__", None)

        if origin is list:
            return "array"
        if origin is dict:
            return "object"

        name = getattr(annotation, "__name__", str(annotation))
        mapping = {
            "str": "string",
            "int": "integer",
            "float": "number",
            "bool": "boolean",
            "list": "array",
            "dict": "object",
        }
        return mapping.get(name, "string")


# sentinel for undefined
undefined = None
