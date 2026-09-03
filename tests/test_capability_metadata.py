"""E5/E6：capability metadata 导出 + permission profiles 校验测试"""

from __future__ import annotations

import json

import pytest

from packages.application.capability import (
    PROFILES,
    check_scope,
    export_capability_metadata,
    get_capability,
    validate_profile,
)


def test_export_capability_metadata():
    data = json.loads(export_capability_metadata())
    assert data["schema_version"] == 1
    assert len(data["capabilities"]) >= 10
    for cap in data["capabilities"]:
        assert cap["name"]
        assert cap["kind"] in ("query", "command", "start_job")
        assert cap["risk"] in ("read_only", "write", "destructive")
        assert cap["required_scope"] in ("research:read", "research:write", "jobs:control", "admin")
        assert "surfaces" in cap


def test_get_capability():
    cap = get_capability("search_papers")
    assert cap.kind == "query"
    with pytest.raises(KeyError):
        get_capability("nonexistent")


def test_validate_profiles():
    assert "research:read" in validate_profile("research")
    assert "admin" in validate_profile("coding")
    assert "jobs:control" not in validate_profile("demo")
    with pytest.raises(ValueError, match="未知 permission profile"):
        validate_profile("nonexistent")


def test_check_scope():
    assert check_scope(["research:read", "research:write"], "research:read") is True
    assert check_scope(["research:read"], "research:write") is False
    assert check_scope(["research:read", "jobs:control"], "jobs:control") is True


def test_demo_never_gets_admin():
    """设计④硬规则：Demo 永不开放 coding/admin"""
    demo_scopes = PROFILES["demo"]
    assert "admin" not in demo_scopes
    assert "jobs:control" not in demo_scopes
