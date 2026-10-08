"""Pi 引擎桥（packages/agent_pi）契约测试。

用 fake pm 脚本（shell → printf 预置 Pi 事件流）验证：
- Pi JSON 事件 → PaperMind SSE 事件的翻译（text_delta/tool_start/tool_result/done）；
- 会话头/未知行被过滤；
- 凭据 env 透传（PAPERMIND_SERVER_URL / PAPERMIND_TOKEN / PAPERMIND_AGENT_DIR）；
- DB 无 active LLM 配置 → 明确报错而非 spawn；
- pm 缺失 → PiEngineUnavailable（路由层回退 python 引擎的契约）。
"""

from __future__ import annotations

import json
import stat
import textwrap

import pytest

from packages.agent_pi import host

FAKE_PM = textwrap.dedent("""\
    #!/bin/sh
    # 回显收到的 env，供断言；然后吐预置 Pi 事件流
    echo "ENV_SERVER_URL=$PAPERMIND_SERVER_URL" >&2
    echo "ENV_TOKEN=$PAPERMIND_TOKEN" >&2
    echo "ENV_AGENT_DIR=$PAPERMIND_AGENT_DIR" >&2
    cat "$FAKE_EVENTS_FILE"
    """)


FAKE_CFG = {
    "provider": "openai",
    "name": "Test Provider",
    "api_key": "sk-test",
    "api_base_url": "https://api.test.com/v1/",
    "model_skim": "gpt-test",
    "model_deep": "gpt-test-deep",
    "model_vision": None,
}


@pytest.fixture()
def fake_pm_env(tmp_path, monkeypatch):
    """fake pm + 预置事件流 + 隔离的 agentDir。"""
    monkeypatch.setattr(host, "_get_active_llm_config", lambda: FAKE_CFG)
    events = [
        {"id": "sess-1", "foo": "bar"},  # 会话头（无 type）→ 应被过滤
        {"type": "agent_start"},
        {
            "type": "message_update",
            "assistantMessageEvent": {"type": "text_delta", "delta": "你好"},
        },
        {
            "type": "message_update",
            "assistantMessageEvent": {"type": "thinking_delta", "delta": "..."},
        },
        {
            "type": "tool_execution_start",
            "toolCallId": "tc1",
            "toolName": "pm_search_papers",
            "args": {"query": "transformer"},
        },
        {
            # E7：破坏性工具的确认请求（onUpdate 透传）
            "type": "tool_execution_update",
            "toolCallId": "tc2",
            "toolName": "pm_submit_job",
            "partialResult": {
                "action_request": {
                    "id": "act-9",
                    "description": "提交 skim_paper 任务处理论文 p1？",
                    "tool": "pm_submit_job",
                    "args": {"capability": "skim_paper", "paper_id": "p1"},
                }
            },
        },
        {
            # 普通进度更新（无 action_request）→ 不翻译
            "type": "tool_execution_update",
            "toolCallId": "tc3",
            "toolName": "pm_search_papers",
            "partialResult": {"progress": "50%"},
        },
        {
            "type": "tool_execution_end",
            "toolCallId": "tc1",
            "toolName": "pm_search_papers",
            "isError": False,
            "result": {
                "content": [{"type": "text", "text": "找到 3 篇论文"}],
                "details": {"total": 3},
            },
        },
        {"type": "message_end", "message": {"role": "assistant", "stopReason": "stop"}},
        {"type": "agent_end"},
    ]
    events_file = tmp_path / "events.jsonl"
    events_file.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in events), encoding="utf-8"
    )

    pm = tmp_path / "fake-pm.sh"
    pm.write_text(FAKE_PM, encoding="utf-8")
    pm.chmod(pm.stat().st_mode | stat.S_IEXEC)

    agent_dir = tmp_path / "web-agent"
    monkeypatch.setattr(host, "PM_BIN", str(pm))
    monkeypatch.setattr(host, "AGENT_DIR", str(agent_dir))
    monkeypatch.setenv("FAKE_EVENTS_FILE", str(events_file))
    return {"pm": pm, "agent_dir": agent_dir, "events_file": events_file}


def _collect(chunks) -> list[tuple[str, dict]]:
    out = []
    for chunk in chunks:
        for m in __import__("re").finditer(
            r"event: (\S+)\ndata: ({.*?})\n\n", chunk, __import__("re").DOTALL
        ):
            out.append((m.group(1), json.loads(m.group(2))))
    return out


def test_translate_full_event_stream(fake_pm_env, monkeypatch):
    """Pi 事件流 → SSE 契约：文本增量/工具卡/完成，thinking 与会话头被过滤"""
    monkeypatch.setattr(host, "SELF_URL", "http://127.0.0.1:8000")
    events = [_collect(host.pi_chat_stream("conv-1", "hi"))]

    (stream,) = events
    kinds = [k for k, _ in stream]
    assert kinds == ["text_delta", "tool_start", "action_confirm", "tool_result", "done"]

    _, tool_start = stream[1]
    assert tool_start["name"] == "pm_search_papers"
    assert tool_start["args"] == {"query": "transformer"}

    # E7：确认卡透传（engine=pi 标记 + 描述 + 参数）
    _, action_confirm = stream[2]
    assert action_confirm["id"] == "act-9"
    assert action_confirm["engine"] == "pi"
    assert action_confirm["tool"] == "pm_submit_job"
    assert "skim_paper" in action_confirm["description"]

    _, tool_result = stream[3]
    assert tool_result["success"] is True
    assert tool_result["summary"] == "找到 3 篇论文"
    assert tool_result["data"] == {"total": 3}


def test_env_passthrough_to_pm(fake_pm_env, monkeypatch):
    """凭据与 agentDir 经 env 透传给 pm（工具回访 API 的链路）"""
    seen = {}

    real_spawn = host.subprocess.Popen

    def spy_spawn(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["env"] = kwargs["env"]
        return real_spawn(cmd, **kwargs)

    monkeypatch.setattr(host.subprocess, "Popen", spy_spawn)
    monkeypatch.setattr(host, "SELF_URL", "http://10.0.0.5:8000")
    list(host.pi_chat_stream("conv-env", "hi", auth_header="Bearer tok-123"))

    env = seen["env"]
    assert env["PAPERMIND_SERVER_URL"] == "http://10.0.0.5:8000"
    assert env["PAPERMIND_TOKEN"] == "tok-123"
    assert env["PAPERMIND_AGENT_DIR"] == str(fake_pm_env["agent_dir"])
    assert seen["cmd"][1:4] == ["-p", "--json", "--session"]


def test_no_active_llm_config_errors_clearly(fake_pm_env, monkeypatch, tmp_path):
    """DB 无 active LLM 配置 → 明确报错 + done，不 spawn pm"""
    monkeypatch.setattr(host, "_get_active_llm_config", lambda: None)
    stream = _collect(host.pi_chat_stream("conv-2", "hi"))
    kinds = [k for k, _ in stream]
    assert kinds == ["error", "done"]
    assert "LLM" in stream[0][1]["message"]


def test_pm_missing_raises_unavailable(monkeypatch):
    """pm 不存在 → pm_binary 为 None / pi_engine_available False（路由层回退）"""
    monkeypatch.setattr(host, "PM_BIN", "/nonexistent/pm")
    monkeypatch.setattr(host.shutil, "which", lambda _: None)
    assert host.pm_binary() is None
    assert host.pi_engine_available() is False


def test_session_file_layout(fake_pm_env):
    """每会话一个 Pi session 文件（web-sessions/<conversation_id>.jsonl）"""
    f = host.session_file_for("abc-123")
    assert f.name == "abc-123.jsonl"
    assert f.parent.name == "web-sessions"


def test_gateway_sidecar_url_mode(monkeypatch):
    """PAPERMIND_GATEWAY_URL（sidecar 形态）：base_url 指向远端、健康即用不 spawn"""
    import importlib

    import packages.agent_pi.gateway as gw

    monkeypatch.setenv("PAPERMIND_GATEWAY_URL", "http://gateway:8765")
    mod = importlib.reload(gw)
    try:
        assert mod.gateway_base_url() == "http://gateway:8765"
        monkeypatch.setattr(mod, "_healthy", lambda: True)
        assert mod.ensure_gateway() == "http://gateway:8765"
        # sidecar 不可达 → None（回退直连），绝不本地 spawn
        monkeypatch.setattr(mod, "_healthy", lambda: False)
        assert mod.ensure_gateway() is None
        assert mod._proc is None
    finally:
        monkeypatch.delenv("PAPERMIND_GATEWAY_URL", raising=False)
        importlib.reload(gw)
