"""
Subagents — 增强型子 Agent 并行调度模块
@author Color2333
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class SubagentStatus(Enum):
    IDLE = "idle"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Subagent:
    id: str
    name: str
    system_prompt: str
    messages: list[dict] = field(default_factory=list)
    status: SubagentStatus = SubagentStatus.IDLE
    result: Any = None
    error: str | None = None


class SubagentRunner:
    def __init__(self, llm_factory: Callable[[], Any]):
        self._llm_factory = llm_factory
        self._subagents: dict[str, Subagent] = {}
        self._lock = threading.Lock()

    def create(self, name: str, system_prompt: str) -> str:
        subagent_id = f"sub_{uuid.uuid4().hex[:8]}"
        with self._lock:
            self._subagents[subagent_id] = Subagent(
                id=subagent_id,
                name=name,
                system_prompt=system_prompt,
                messages=[{"role": "system", "content": system_prompt}],
            )
        return subagent_id

    def run_sync(
        self,
        subagent_id: str,
        task: str,
        timeout: int = 120,
    ) -> dict:
        subagent = self._subagents.get(subagent_id)
        if not subagent:
            return {"success": False, "error": f"Subagent {subagent_id} not found"}
        subagent.status = SubagentStatus.RUNNING
        subagent.messages.append({"role": "user", "content": task})
        result_holder: dict = {}

        def _run():
            try:
                llm = self._llm_factory()
                response = llm.chat_stream(subagent.messages, tools=[])
                text_parts = []
                for event in response:
                    if event.type == "text_delta":
                        text_parts.append(event.content)
                subagent.result = "".join(text_parts)
                subagent.messages.append({"role": "assistant", "content": subagent.result})
                subagent.status = SubagentStatus.DONE
                result_holder["success"] = True
                result_holder["result"] = subagent.result
            except Exception as exc:  # noqa: BLE001
                subagent.status = SubagentStatus.FAILED
                subagent.error = str(exc)
                result_holder["success"] = False
                result_holder["error"] = str(exc)

        thread = threading.Thread(target=_run)
        thread.start()
        thread.join(timeout=timeout)
        if thread.is_alive():
            subagent.status = SubagentStatus.FAILED
            subagent.error = "Timeout"
            return {"success": False, "error": "Timeout"}
        return result_holder or {"success": False, "error": "No result"}

    def run_async(self, subagent_id: str, task: str) -> None:
        subagent = self._subagents.get(subagent_id)
        if not subagent:
            logger.warning("run_async: subagent %s not found", subagent_id)
            return
        subagent.status = SubagentStatus.RUNNING
        subagent.messages.append({"role": "user", "content": task})

        def _run():
            try:
                llm = self._llm_factory()
                response = llm.chat_stream(subagent.messages, tools=[])
                text_parts = []
                for event in response:
                    if event.type == "text_delta":
                        text_parts.append(event.content)
                subagent.result = "".join(text_parts)
                subagent.messages.append({"role": "assistant", "content": subagent.result})
                subagent.status = SubagentStatus.DONE
            except Exception as exc:  # noqa: BLE001
                subagent.status = SubagentStatus.FAILED
                subagent.error = str(exc)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

    def poll(self, subagent_id: str) -> dict:
        subagent = self._subagents.get(subagent_id)
        if not subagent:
            return {"status": "not_found"}
        return {
            "id": subagent.id,
            "name": subagent.name,
            "status": subagent.status.value,
            "result": subagent.result if subagent.status == SubagentStatus.DONE else None,
            "error": subagent.error,
        }

    def collect_result(self, subagent_id: str) -> Any:
        subagent = self._subagents.get(subagent_id)
        if not subagent:
            return None
        while subagent.status == SubagentStatus.RUNNING:
            threading.Event().wait(0.1)
        return subagent.result

    def kill(self, subagent_id: str) -> None:
        subagent = self._subagents.get(subagent_id)
        if subagent and subagent.status == SubagentStatus.RUNNING:
            subagent.status = SubagentStatus.FAILED
            subagent.error = "Killed by caller"

    def list_subagents(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "id": s.id,
                    "name": s.name,
                    "status": s.status.value,
                }
                for s in self._subagents.values()
            ]


class SubagentPool:
    def __init__(self, max_concurrent: int = 3):
        self._max_concurrent = max_concurrent
        self._runners: dict[str, SubagentRunner] = {}
        self._runner_lock = threading.Lock()
        self._active_count = 0
        self._active_lock = threading.Lock()

    def create_runner(self, name: str, system_prompt: str) -> str:
        llm_factory = self._get_llm_factory()
        runner = SubagentRunner(llm_factory)
        runner_id = runner.create(name, system_prompt)
        with self._runner_lock:
            self._runners[runner_id] = runner
        return runner_id

    def run_parallel(self, tasks: list[dict[str, str]]) -> list[dict]:
        results = []
        for task_def in tasks[: self._max_concurrent]:
            runner_id = self.create_runner(task_def["name"], f"You are {task_def['name']}.")
            runner = self._get_runner(runner_id)
            if runner:
                result = runner.run_sync(runner_id, task_def["task"])
                results.append({"name": task_def["name"], **result})
        return results

    def get_runner(self, runner_id: str) -> SubagentRunner | None:
        return self._runners.get(runner_id)

    def list_runners(self) -> list[dict]:
        with self._runner_lock:
            all_results = []
            for _rid, runner in self._runners.items():
                all_results.extend(runner.list_subagents())
            return all_results

    def shutdown(self) -> None:
        with self._runner_lock:
            for _runner in self._runners.values():
                pass
            self._runners.clear()

    def _get_llm_factory(self) -> Callable[[], Any]:
        def factory() -> Any:
            from packages.integrations.llm_client import LLMClient

            return LLMClient()

        return factory

    def _get_runner(self, runner_id: str) -> SubagentRunner | None:
        return self._runners.get(runner_id)


_global_pool: SubagentPool | None = None
_pool_lock = threading.Lock()


def get_subagent_pool(max_concurrent: int = 3) -> SubagentPool:
    global _global_pool
    with _pool_lock:
        if _global_pool is None:
            _global_pool = SubagentPool(max_concurrent=max_concurrent)
        return _global_pool
