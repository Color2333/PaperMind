"""C4：原子 Task 能力注册表不变量测试

- 每个能力的 handler 必须可导入且符号存在；
- idempotency 模板、timeout、resource class 必须合法；
- manual_recovery=True 的能力 max_attempts 必须为 1；
- resource class 与设计③第一批清单一致。
"""

from __future__ import annotations

import importlib

import pytest

from packages.application.commands.task_registry import (
    RESOURCE_CLASSES,
    TASK_CAPABILITIES,
    get_spec,
    specs_for_resource_class,
)

REQUIRED_FIRST_BATCH = {
    "fetch_feed",
    "upsert_paper",
    "download_source",
    "skim_paper",
    "deep_read_paper",
    "extract_claims",
    "embed_paper",
    "generate_topic_wiki",
    "build_daily_brief",
    "send_brief_email",
}


def test_first_batch_registered():
    assert set(TASK_CAPABILITIES) >= REQUIRED_FIRST_BATCH


@pytest.mark.parametrize("name", sorted(TASK_CAPABILITIES))
def test_handler_importable(name):
    spec = TASK_CAPABILITIES[name]
    module_path, symbol = spec.handler.split(":")
    module = importlib.import_module(module_path)
    obj = module
    for part in symbol.split("."):
        obj = getattr(obj, part)
    assert callable(obj)


@pytest.mark.parametrize("name", sorted(TASK_CAPABILITIES))
def test_spec_invariants(name):
    spec = get_spec(name)
    assert spec.timeout_s > 0
    assert spec.max_attempts >= 1
    assert spec.resource_class in RESOURCE_CLASSES
    assert spec.idempotency_template and "{" in spec.idempotency_template
    assert spec.side_effect, "单一有意义副作用必须显式描述"
    # manual_recovery 能力禁止自动重试
    if spec.manual_recovery:
        assert spec.max_attempts == 1
    # 重试能力不可能是邮件类
    if not spec.manual_recovery:
        assert "mail" not in spec.idempotency_template


def test_resource_classes_covered():
    # 设计③第一批至少覆盖 llm/embedding/network/default 四类
    for rc in RESOURCE_CLASSES:
        assert specs_for_resource_class(rc), f"资源类别 {rc} 无已登记能力"


def test_get_spec_unknown_raises():
    with pytest.raises(KeyError):
        get_spec("not_a_capability")
