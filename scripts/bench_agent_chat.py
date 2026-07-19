"""Agent 后端 Benchmark：老 StreamingAgentLoop (v1 /agent/chat) vs 新 LangGraph PoC (v2 /agent/v2/chat)

对比 4 个指标：端到端 SSE 总时长、首 token 延迟 (TTFT)、工具往返延迟、token 消耗。

前提：
- 本地 uvicorn 已起（apps.api.main:app --port <PORT>），.env 配好 LLM key
- 两后端共用 LLMClient.chat_stream + execute_tool_stream，LLM/工具延迟相同，
  端到端 delta 归因于 LangGraph 图编译 + LangChain 消息转换 + MemorySaver checkpoint

Usage:
    python scripts/bench_agent_chat.py [--port 8010] [--runs 5] [--out bench_results.json]

@author Color2333
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

# ---------- 配置 ----------

_SSE_EVENT_RE = re.compile(r"event:\s*(\S+)\s*\ndata:\s*(\{.*?\})\s*\n\n", re.DOTALL)

# 5 个场景：prompt 触发不同工具/流程
SCENARIOS: list[dict] = [
    {"name": "普通对话", "prompt": "用一句话介绍你自己", "kind": "chat"},
    {"name": "list_topics", "prompt": "调用 list_topics 工具列出所有订阅主题", "kind": "chat"},
    {
        "name": "get_batch_job_status",
        "prompt": "调用 get_batch_job_status 工具查 job_id=test-bench-001 的状态",
        "kind": "chat",
    },
    {
        "name": "get_citation_tree",
        "prompt": "调用 get_citation_tree 工具查论文 11111111-2222-3333-4444-555555555555 的引用树",
        "kind": "chat",
    },
    {
        "name": "skim_paper confirm",
        "prompt": "调用 skim_paper 工具粗读论文 11111111-2222-3333-4444-555555555555",
        "kind": "confirm",
    },
]

# 两后端路由
BACKENDS = {
    "v1": {"chat": "/agent/chat", "confirm": "/agent/confirm", "reject": "/agent/reject"},
    "v2": {"chat": "/agent/v2/chat", "confirm": "/agent/v2/confirm", "reject": "/agent/v2/reject"},
}


# ---------- 辅助 ----------


def mint_token() -> str:
    """mint JWT token via packages.auth（复用 .env auth_secret_key）。"""
    from packages.auth import create_access_token

    return create_access_token({"sub": "papermind-user"})


def parse_sse_chunk(buf: str) -> tuple[list[tuple[str, dict]], str]:
    """从 SSE 文本缓冲解析已完成事件，返回 (events, 剩余未完成 buf)。"""
    events: list[tuple[str, dict]] = []
    last_end = 0
    for match in _SSE_EVENT_RE.finditer(buf):
        try:
            data = json.loads(match.group(2))
            events.append((match.group(1), data))
        except json.JSONDecodeError:
            pass
        last_end = match.end()
    return events, buf[last_end:]


def run_once(
    base: str,
    backend: str,
    prompt: str,
    token: str,
    conversation_id: str | None = None,
    timeout: float = 90.0,
) -> dict:
    """单次请求：流式读 SSE，记录事件时间戳。返回指标 dict。

    返回：{ttft, e2e, tool_roundtrips: [{id, name, latency}], conversation_id, action_id, events: [(type, t)]}
    """
    chat_path = BACKENDS[backend]["chat"]
    url = f"{base}{chat_path}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    body = json.dumps(
        {"messages": [{"role": "user", "content": prompt}], "conversation_id": conversation_id}
    )

    t0 = time.perf_counter()
    ttft: float | None = None
    e2e: float | None = None
    tool_roundtrips: list[dict] = []
    tool_starts: dict[str, tuple[float, str]] = {}  # id → (t, name)
    conv_id: str | None = None
    action_id: str | None = None

    with httpx.stream("POST", url, headers=headers, content=body, timeout=timeout) as resp:
        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}: {resp.read().decode()[:200]}"}
        buf = ""
        for chunk in resp.iter_text():
            t = time.perf_counter() - t0
            buf += chunk
            events, buf = parse_sse_chunk(buf)
            for etype, data in events:
                if etype == "conversation_init":
                    conv_id = data.get("conversation_id")
                elif etype == "text_delta" and ttft is None:
                    ttft = t
                elif etype == "tool_start":
                    tool_starts[data.get("id")] = (t, data.get("name"))
                elif etype == "tool_result":
                    tid = data.get("id")
                    if tid in tool_starts:
                        start_t, name = tool_starts.pop(tid)
                        tool_roundtrips.append({"id": tid, "name": name, "latency": t - start_t})
                elif etype == "action_confirm":
                    action_id = data.get("id")
                elif etype == "done":
                    e2e = t

    return {
        "ttft": ttft,
        "e2e": e2e,
        "tool_roundtrips": tool_roundtrips,
        "conversation_id": conv_id,
        "action_id": action_id,
    }


def run_confirm_flow(
    base: str, backend: str, prompt: str, token: str, max_retries: int = 2
) -> dict:
    """confirm 流：触发 interrupt → 拿 action_id → confirm resume → 合并两请求 e2e。

    LLM 可能不调 confirm 工具（非确定性），允许 max_retries 次重试触发。
    """
    last_err: str | None = None
    for _attempt in range(max_retries):
        # 第一次请求：触发 interrupt
        first = run_once(base, backend, prompt, token)
        if "error" in first:
            return first
        if not first.get("action_id"):
            last_err = f"未触发 action_confirm（LLM 未调 confirm 工具），conv={first.get('conversation_id')}"
            time.sleep(0.5)
            continue

        action_id = first["action_id"]
        conv_id = first["conversation_id"]
        break
    else:
        return {"error": last_err or "触发 confirm 失败"}
    # 第二次请求：confirm resume
    confirm_path = BACKENDS[backend]["confirm"]
    url = f"{base}{confirm_path}/{action_id}"
    headers = {"Authorization": f"Bearer {token}"}
    t0 = time.perf_counter()
    e2e_confirm: float | None = None
    tool_roundtrips2: list[dict] = []
    tool_starts: dict[str, tuple[float, str]] = {}
    ttft2: float | None = None

    with httpx.stream("POST", url, headers=headers, timeout=120.0) as resp:
        if resp.status_code != 200:
            return {"error": f"confirm HTTP {resp.status_code}: {resp.read().decode()[:200]}"}
        buf = ""
        for chunk in resp.iter_text():
            t = time.perf_counter() - t0
            buf += chunk
            events, buf = parse_sse_chunk(buf)
            for etype, data in events:
                if etype == "text_delta" and ttft2 is None:
                    ttft2 = t
                elif etype == "tool_start":
                    tool_starts[data.get("id")] = (t, data.get("name"))
                elif etype == "tool_result":
                    tid = data.get("id")
                    if tid in tool_starts:
                        start_t, name = tool_starts.pop(tid)
                        tool_roundtrips2.append({"id": tid, "name": name, "latency": t - start_t})
                elif etype == "done":
                    e2e_confirm = t

    # 合并：触发请求 e2e + confirm 请求 e2e = confirm 流总延迟
    total_e2e = (first.get("e2e") or 0) + (e2e_confirm or 0)
    return {
        "e2e_trigger": first.get("e2e"),
        "e2e_confirm": e2e_confirm,
        "e2e_total": total_e2e,
        "ttft_confirm": ttft2,
        "tool_roundtrips": first["tool_roundtrips"] + tool_roundtrips2,
        "conversation_id": conv_id,
        "action_id": action_id,
    }


def collect_tokens(t0: datetime, t1: datetime) -> dict:
    """查 prompt_traces 表按时间窗口统计 token。"""
    try:
        from sqlalchemy import select

        from packages.storage.db import session_scope
        from packages.storage.models import PromptTrace

        with session_scope() as s:
            q = select(PromptTrace).where(
                PromptTrace.stage == "agent_chat",
                PromptTrace.created_at >= t0,
                PromptTrace.created_at <= t1,
            )
            rows = list(s.execute(q).scalars())
            total_in = sum(r.input_tokens or 0 for r in rows)
            total_out = sum(r.output_tokens or 0 for r in rows)
            return {
                "count": len(rows),
                "input_tokens_total": total_in,
                "output_tokens_total": total_out,
            }
    except Exception as exc:
        return {"error": str(exc)}


def summarize(values: list[float | None]) -> dict:
    """计算 mean/p50/p95/min/max（忽略 None）。"""
    valid = [v for v in values if v is not None]
    if not valid:
        return {"mean": None, "p50": None, "p95": None, "min": None, "max": None, "n": 0}
    valid_sorted = sorted(valid)
    n = len(valid_sorted)
    p50_idx = n // 2
    p95_idx = max(0, int(n * 0.95) - 1)
    return {
        "mean": statistics.mean(valid),
        "p50": valid_sorted[p50_idx],
        "p95": valid_sorted[p95_idx],
        "min": valid_sorted[0],
        "max": valid_sorted[-1],
        "n": n,
    }


def fmt_secs(s: float | None) -> str:
    if s is None:
        return "  N/A"
    return f"{s:.3f}s"


def fmt_delta(v2: float | None, v1: float | None) -> str:
    if v2 is None or v1 is None or v1 == 0:
        return "  N/A"
    pct = (v2 - v1) / v1 * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


# ---------- 主流程 ----------


def run_benchmark(port: int, runs: int, out_path: str) -> dict:
    base = f"http://127.0.0.1:{port}"
    print("=== Agent 后端 Benchmark ===")
    print(f"target: {base}  runs per scenario: {runs}\n")

    # 健康检查
    try:
        h = httpx.get(f"{base}/health", timeout=5)
        if h.status_code != 200:
            print(f"FAIL: 后端不可用 /health → {h.status_code}")
            sys.exit(1)
        print(f"health: {h.json()}\n")
    except Exception as exc:
        print(f"FAIL: 无法连接后端 {base}: {exc}")
        sys.exit(1)

    token = mint_token()
    t0 = datetime.now(UTC)
    all_results: dict = {
        "scenarios": [],
        "meta": {"port": port, "runs": runs, "t0": t0.isoformat()},
    }

    for sc in SCENARIOS:
        sc_name = sc["name"]
        kind = sc["kind"]
        prompt = sc["prompt"]
        print(f"--- 场景 {SCENARIOS.index(sc) + 1}: {sc_name} ({kind}) ---")

        sc_result: dict = {
            "name": sc_name,
            "kind": kind,
            "prompt": prompt,
            "backends": {"v1": {"runs": []}, "v2": {"runs": []}},
        }

        # 交替跑 v1/v2（v1, v2, v1, v2, ...）平衡 LLM 冷热/网络抖动
        for i in range(runs):
            for backend in ["v1", "v2"]:
                BACKENDS[backend]["chat"]
                if kind == "confirm":
                    r = run_confirm_flow(base, backend, prompt, token)
                else:
                    r = run_once(base, backend, prompt, token)
                sc_result["backends"][backend]["runs"].append(r)
                if "error" in r:
                    print(f"  [{backend}] run {i + 1}: ERROR {r['error'][:80]}")
                else:
                    if kind == "confirm":
                        print(
                            f"  [{backend}] run {i + 1}: e2e_total={fmt_secs(r.get('e2e_total'))} "
                            f"(trigger={fmt_secs(r.get('e2e_trigger'))} + confirm={fmt_secs(r.get('e2e_confirm'))})"
                        )
                    else:
                        print(
                            f"  [{backend}] run {i + 1}: ttft={fmt_secs(r.get('ttft'))} "
                            f"e2e={fmt_secs(r.get('e2e'))} "
                            f"tools={len(r.get('tool_roundtrips', []))}"
                        )
                time.sleep(0.5)  # 请求间隔，避免限流

        # 聚合每个后端
        for backend in ["v1", "v2"]:
            runs_data = sc_result["backends"][backend]["runs"]
            if kind == "confirm":
                summary = {
                    "e2e_total": summarize(
                        [r.get("e2e_total") for r in runs_data if "error" not in r]
                    ),
                    "e2e_trigger": summarize(
                        [r.get("e2e_trigger") for r in runs_data if "error" not in r]
                    ),
                    "e2e_confirm": summarize(
                        [r.get("e2e_confirm") for r in runs_data if "error" not in r]
                    ),
                    "ttft_confirm": summarize(
                        [r.get("ttft_confirm") for r in runs_data if "error" not in r]
                    ),
                }
            else:
                summary = {
                    "ttft": summarize([r.get("ttft") for r in runs_data if "error" not in r]),
                    "e2e": summarize([r.get("e2e") for r in runs_data if "error" not in r]),
                    "tool_roundtrips": summarize(
                        [
                            statistics.mean([tr["latency"] for tr in r.get("tool_roundtrips", [])])
                            for r in runs_data
                            if "error" not in r and r.get("tool_roundtrips")
                        ]
                    ),
                }
            sc_result["backends"][backend]["summary"] = summary

        # 打印对比表
        print(f"\n  {'指标':<18} {'v1 mean':<12} {'v2 mean':<12} {'delta':<10}")
        v1s = sc_result["backends"]["v1"]["summary"]
        v2s = sc_result["backends"]["v2"]["summary"]
        if kind == "confirm":
            for metric, label in [
                ("e2e_total", "E2E 总时长"),
                ("e2e_trigger", "触发耗时"),
                ("e2e_confirm", "确认耗时"),
                ("ttft_confirm", "确认TTFT"),
            ]:
                v1m = v1s[metric]["mean"]
                v2m = v2s[metric]["mean"]
                print(
                    f"  {label:<18} {fmt_secs(v1m):<12} {fmt_secs(v2m):<12} {fmt_delta(v2m, v1m):<10}"
                )
        else:
            for metric, label in [
                ("ttft", "TTFT"),
                ("e2e", "E2E 总时长"),
                ("tool_roundtrips", "工具往返"),
            ]:
                v1m = v1s[metric]["mean"]
                v2m = v2s[metric]["mean"]
                print(
                    f"  {label:<18} {fmt_secs(v1m):<12} {fmt_secs(v2m):<12} {fmt_delta(v2m, v1m):<10}"
                )
        print()

        all_results["scenarios"].append(sc_result)

    # token 统计
    t1 = datetime.now(UTC)
    tokens = collect_tokens(t0, t1)
    all_results["meta"]["t1"] = t1.isoformat()
    all_results["tokens"] = tokens
    print(f"=== token 统计（{t0.strftime('%H:%M:%S')} ~ {t1.strftime('%H:%M:%S')}）===")
    print(f"  prompt_traces (stage=agent_chat): {tokens}")
    print("  注：v1/v2 共用 stage，无法直接区分；token 一致性靠 LLM 调用相同保证")

    # 写 JSON
    out_file = Path(out_path)
    out_file.write_text(json.dumps(all_results, ensure_ascii=False, indent=2, default=str))
    print(f"\n原始数据写入: {out_file}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent 后端 benchmark：v1 vs v2")
    parser.add_argument("--port", type=int, default=8010, help="本地 uvicorn 端口")
    parser.add_argument("--runs", type=int, default=5, help="每场景跑几次")
    parser.add_argument("--out", type=str, default="bench_results.json", help="JSON 输出路径")
    args = parser.parse_args()
    run_benchmark(args.port, args.runs, args.out)


if __name__ == "__main__":
    main()
