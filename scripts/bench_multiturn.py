"""多轮 Agent Benchmark + 真实任务案例对比。

两场景（同一 conversation_id，10 轮）：
- 场景 A：10 轮纯对话增长曲线（隔离历史拼接开销）
- 场景 B：10 轮含 confirm（第 3/6/9 轮触发 skim_paper），测 confirm 状态存/读开销

真实任务案例：
- 跑一个多工具任务（search_papers + skim_paper + ask_knowledge_base），v1/v2 各一遍
- 对比总耗时 / 工具调用轮次 / token / LLM 决策路径

Usage:
    python scripts/bench_multiturn.py [--port 8010] [--rounds 10] [--out bench_multiturn.json]

@author Color2333
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

_SSE_EVENT_RE = re.compile(r"event:\s*(\S+)\s*\ndata:\s*(\{.*?\})\s*\n\n", re.DOTALL)

BACKENDS = {
    "v1": {"chat": "/agent/chat", "confirm": "/agent/confirm", "reject": "/agent/reject"},
    "v2": {"chat": "/agent/v2/chat", "confirm": "/agent/v2/confirm", "reject": "/agent/v2/reject"},
}


def mint_token() -> str:
    from packages.auth import create_access_token

    return create_access_token({"sub": "papermind-user"})


def parse_sse_chunk(buf: str) -> tuple[list[tuple[str, dict]], str]:
    events: list[tuple[str, dict]] = []
    last_end = 0
    for match in _SSE_EVENT_RE.finditer(buf):
        with contextlib.suppress(json.JSONDecodeError):
            events.append((match.group(1), json.loads(match.group(2))))
        last_end = match.end()
    return events, buf[last_end:]


def run_once(
    base: str,
    backend: str,
    prompt: str,
    token: str,
    conversation_id: str | None = None,
    timeout: float = 120.0,
) -> dict:
    """单次请求，记录事件时间戳 + 完整事件序列。"""
    chat_path = BACKENDS[backend]["chat"]
    url = f"{base}{chat_path}"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    body = json.dumps(
        {"messages": [{"role": "user", "content": prompt}], "conversation_id": conversation_id}
    )

    t0 = time.perf_counter()
    ttft: float | None = None
    e2e: float | None = None
    tool_roundtrips: list[dict] = []
    tool_starts: dict[str, tuple[float, str]] = {}
    conv_id: str | None = None
    action_id: str | None = None
    event_log: list[dict] = []  # 完整事件序列（案例用）

    with httpx.stream("POST", url, headers=headers, content=body, timeout=timeout) as resp:
        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}: {resp.read().decode()[:200]}"}
        buf = ""
        for chunk in resp.iter_text():
            t = time.perf_counter() - t0
            buf += chunk
            events, buf = parse_sse_chunk(buf)
            for etype, data in events:
                event_log.append({"type": etype, "t": t, "data": data})
                if etype == "conversation_init":
                    conv_id = data.get("conversation_id")
                elif etype == "text_delta" and ttft is None:
                    ttft = t
                elif etype == "tool_start":
                    tool_starts[data.get("id")] = (t, data.get("name"))
                    event_log[-1]["tool_name"] = data.get("name")
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
        "events": event_log,
    }


def run_confirm_resume(
    base: str,
    backend: str,
    action_id: str,
    token: str,
    conv_id: str | None = None,
    timeout: float = 120.0,
) -> dict:
    """confirm resume 第二请求，记录 e2e + 事件。"""
    confirm_path = BACKENDS[backend]["confirm"]
    url = f"{base}{confirm_path}/{action_id}"
    headers = {"Authorization": f"Bearer {token}"}
    t0 = time.perf_counter()
    e2e: float | None = None
    ttft: float | None = None
    tool_roundtrips: list[dict] = []
    tool_starts: dict[str, tuple[float, str]] = {}
    event_log: list[dict] = []

    with httpx.stream("POST", url, headers=headers, timeout=timeout) as resp:
        if resp.status_code != 200:
            return {"error": f"confirm HTTP {resp.status_code}: {resp.read().decode()[:200]}"}
        buf = ""
        for chunk in resp.iter_text():
            t = time.perf_counter() - t0
            buf += chunk
            events, buf = parse_sse_chunk(buf)
            for etype, data in events:
                event_log.append({"type": etype, "t": t, "data": data})
                if etype == "text_delta" and ttft is None:
                    ttft = t
                elif etype == "tool_start":
                    tool_starts[data.get("id")] = (t, data.get("name"))
                elif etype == "tool_result":
                    tid = data.get("id")
                    if tid in tool_starts:
                        start_t, name = tool_starts.pop(tid)
                        tool_roundtrips.append({"id": tid, "name": name, "latency": t - start_t})
                elif etype == "done":
                    e2e = t

    return {"e2e": e2e, "ttft": ttft, "tool_roundtrips": tool_roundtrips, "events": event_log}


def collect_tokens_in_window(t0: datetime, t1: datetime) -> list[dict]:
    """查 prompt_traces 表时间窗口内的记录，返回每条 token 信息。"""
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
            return [
                {
                    "input_tokens": r.input_tokens,
                    "output_tokens": r.output_tokens,
                    "created_at": r.created_at.isoformat(),
                }
                for r in s.execute(q).scalars()
            ]
    except Exception as exc:
        return [{"error": str(exc)}]


# ---------- 场景 A：10 轮纯对话增长曲线 ----------


def run_scenario_a(base: str, backend: str, token: str, rounds: int) -> dict:
    """同一 conversation_id 连发 rounds 轮，每轮不调工具，测 TTFT/E2E 增长。"""
    print(f"  [{backend}] 场景 A：{rounds} 轮纯对话")
    conv_id: str | None = None
    results: list[dict] = []
    # 引导 LLM 不调工具的 prompt（每轮换内容避免被缓存）
    prompts = [
        f"第{i + 1}轮：用一句话简短回复我刚才说了什么（不要调用任何工具）" for i in range(rounds)
    ]
    for i, prompt in enumerate(prompts):
        r = run_once(base, backend, prompt, token, conversation_id=conv_id)
        if "error" in r:
            print(f"    轮 {i + 1}: ERROR {r['error'][:60]}")
            results.append({"error": r["error"]})
            continue
        if conv_id is None:
            conv_id = r["conversation_id"]
        results.append(
            {
                "round": i + 1,
                "ttft": r["ttft"],
                "e2e": r["e2e"],
                "tools": len(r["tool_roundtrips"]),
            }
        )
        print(
            f"    轮 {i + 1}: ttft={fmt_secs(r['ttft'])} e2e={fmt_secs(r['e2e'])} "
            f"tools={len(r['tool_roundtrips'])}"
        )
        time.sleep(0.5)
    return {"conversation_id": conv_id, "rounds": results}


# ---------- 场景 B：10 轮含 confirm 累计延迟 ----------


def run_scenario_b(
    base: str, backend: str, token: str, rounds: int, confirm_rounds: list[int]
) -> dict:
    """含 confirm 的多轮。confirm_rounds 指定哪些轮触发 skim_paper。"""
    print(f"  [{backend}] 场景 B：{rounds} 轮，第 {confirm_rounds} 轮触发 confirm")
    conv_id: str | None = None
    results: list[dict] = []
    for i in range(rounds):
        round_num = i + 1
        is_confirm = round_num in confirm_rounds
        if is_confirm:
            prompt = f"第{round_num}轮：调用 skim_paper 工具粗读论文 11111111-2222-3333-4444-555555555555"
        else:
            prompt = f"第{round_num}轮：用一句话简短回复（不要调用任何工具）"

        first = run_once(base, backend, prompt, token, conversation_id=conv_id)
        if "error" in first:
            print(f"    轮 {round_num}: ERROR {first['error'][:60]}")
            results.append({"round": round_num, "error": first["error"]})
            continue
        if conv_id is None:
            conv_id = first["conversation_id"]

        if is_confirm and first.get("action_id"):
            # confirm resume
            confirm = run_confirm_resume(base, backend, first["action_id"], token, conv_id)
            trigger_e2e = first.get("e2e") or 0.0
            confirm_e2e = confirm.get("e2e") or 0.0
            total_e2e = trigger_e2e + confirm_e2e
            results.append(
                {
                    "round": round_num,
                    "kind": "confirm",
                    "e2e_trigger": trigger_e2e or None,
                    "e2e_confirm": confirm_e2e or None,
                    "e2e_total": total_e2e or None,
                    "action_id": first["action_id"],
                }
            )
            print(
                f"    轮 {round_num}(confirm): trigger={fmt_secs(trigger_e2e or None)} "
                f"confirm={fmt_secs(confirm_e2e or None)} total={fmt_secs(total_e2e or None)}"
            )
        else:
            results.append(
                {
                    "round": round_num,
                    "kind": "chat" if not is_confirm else "confirm_failed",
                    "ttft": first.get("ttft"),
                    "e2e": first.get("e2e"),
                    "tools": len(first.get("tool_roundtrips", [])),
                }
            )
            kind_tag = "chat" if not is_confirm else "confirm(未触发)"
            print(
                f"    轮 {round_num}({kind_tag}): ttft={fmt_secs(first.get('ttft'))} "
                f"e2e={fmt_secs(first.get('e2e'))}"
            )
        time.sleep(0.5)
    return {"conversation_id": conv_id, "rounds": results}


# ---------- 真实任务案例 ----------

EFFICIENCY_TASK_PROMPT = (
    "请完成这个任务：先调用 search_papers 工具搜索关键词 'attention'（limit=3），"
    "然后用 skim_paper 工具粗读搜索结果中的第一篇论文，"
    "最后用一句话总结这篇论文的核心贡献。"
)


def run_efficiency_case(base: str, backend: str, token: str) -> dict:
    """跑一个完整多工具任务，记录全部事件序列 + 总耗时 + 工具路径。"""
    print(f"  [{backend}] 效率案例：多工具任务（search → skim → 总结）")
    t0 = datetime.now(UTC)
    result = run_once(base, backend, EFFICIENCY_TASK_PROMPT, token)
    t1 = datetime.now(UTC)

    if "error" in result:
        return {"error": result["error"]}

    # 分析事件序列
    event_types = [e["type"] for e in result["events"]]
    tool_calls = [e for e in result["events"] if e["type"] == "tool_start"]
    tool_names = [e["data"].get("name") for e in tool_calls]
    action_confirms = [e for e in result["events"] if e["type"] == "action_confirm"]

    # token 查表
    tokens = collect_tokens_in_window(t0, t1)

    analysis = {
        "backend": backend,
        "total_e2e": result["e2e"],
        "ttft": result["ttft"],
        "tool_calls": [{"name": n} for n in tool_names],
        "tool_call_count": len(tool_names),
        "tool_call_sequence": tool_names,
        "has_action_confirm": len(action_confirms) > 0,
        "action_confirm_count": len(action_confirms),
        "event_type_counts": {t: event_types.count(t) for t in set(event_types)},
        "tokens": tokens,
    }
    print(
        f"    e2e={fmt_secs(result['e2e'])} ttft={fmt_secs(result['ttft'])} "
        f"tools={len(tool_names)} ({tool_names})"
    )
    return analysis


# ---------- 主流程 ----------


def fmt_secs(s: float | None) -> str:
    if s is None:
        return "  N/A"
    return f"{s:.3f}s"


def run_benchmark(port: int, rounds: int, out_path: str) -> dict:
    base = f"http://127.0.0.1:{port}"
    print("=== 多轮 Agent Benchmark + 案例对比 ===")
    print(f"target: {base}  rounds per scenario: {rounds}\n")

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
    confirm_rounds = [3, 6, 9]
    all_results: dict = {"meta": {"port": port, "rounds": rounds, "confirm_rounds": confirm_rounds}}

    # ---------- 场景 A ----------
    print("--- 场景 A：10 轮纯对话增长曲线 ---")
    all_results["scenario_a"] = {}
    for backend in ["v1", "v2"]:
        all_results["scenario_a"][backend] = run_scenario_a(base, backend, token, rounds)

    # 打印增长曲线对比
    print("\n  增长曲线对比（TTFT / E2E 随轮次）：")
    print(f"  {'轮次':<6} {'v1 TTFT':<12} {'v2 TTFT':<12} {'v1 E2E':<12} {'v2 E2E':<12}")
    v1a = all_results["scenario_a"]["v1"]["rounds"]
    v2a = all_results["scenario_a"]["v2"]["rounds"]
    for i in range(min(len(v1a), len(v2a))):
        v1r = v1a[i] if "error" not in v1a[i] else {}
        v2r = v2a[i] if "error" not in v2a[i] else {}
        print(
            f"  {i + 1:<6} {fmt_secs(v1r.get('ttft')):<12} {fmt_secs(v2r.get('ttft')):<12} "
            f"{fmt_secs(v1r.get('e2e')):<12} {fmt_secs(v2r.get('e2e')):<12}"
        )

    # 增长率：最后一轮 vs 第一轮
    def growth_rate(rounds_list: list, key: str) -> str:
        valid = [r for r in rounds_list if "error" not in r and r.get(key)]
        if len(valid) < 2:
            return "N/A"
        first = valid[0][key]
        last = valid[-1][key]
        if first == 0:
            return "N/A"
        return f"{(last - first) / first * 100:+.1f}%"

    print(f"\n  v1 TTFT 增长率: {growth_rate(v1a, 'ttft')}")
    print(f"  v2 TTFT 增长率: {growth_rate(v2a, 'ttft')}")
    print(f"  v1 E2E 增长率: {growth_rate(v1a, 'e2e')}")
    print(f"  v2 E2E 增长率: {growth_rate(v2a, 'e2e')}")
    print()

    # ---------- 场景 B ----------
    print("--- 场景 B：10 轮含 confirm 累计延迟 ---")
    all_results["scenario_b"] = {}
    for backend in ["v1", "v2"]:
        all_results["scenario_b"][backend] = run_scenario_b(
            base, backend, token, rounds, confirm_rounds
        )

    # 打印 confirm 累计延迟对比
    print("\n  confirm 轮累计延迟对比：")
    print(f"  {'轮次':<6} {'类型':<14} {'v1 e2e_total':<14} {'v2 e2e_total':<14} {'delta':<10}")
    v1b = all_results["scenario_b"]["v1"]["rounds"]
    v2b = all_results["scenario_b"]["v2"]["rounds"]
    for i in range(min(len(v1b), len(v2b))):
        v1r = v1b[i] if "error" not in v1b[i] else {}
        v2r = v2b[i] if "error" not in v2b[i] else {}
        kind = v1r.get("kind", "?")
        v1e = v1r.get("e2e_total") or v1r.get("e2e")
        v2e = v2r.get("e2e_total") or v2r.get("e2e")
        if v1e and v2e:
            delta = f"{(v2e - v1e) / v1e * 100:+.1f}%"
        else:
            delta = "N/A"
        print(f"  {i + 1:<6} {kind:<14} {fmt_secs(v1e):<14} {fmt_secs(v2e):<14} {delta:<10}")
    print()

    # ---------- 效率案例 ----------
    print("--- 真实多工具任务案例 ---")
    print(f"  任务: {EFFICIENCY_TASK_PROMPT[:60]}...")
    all_results["efficiency_case"] = {}
    for backend in ["v1", "v2"]:
        all_results["efficiency_case"][backend] = run_efficiency_case(base, backend, token)

    # 打印案例对比
    v1c = all_results["efficiency_case"]["v1"]
    v2c = all_results["efficiency_case"]["v2"]
    print("\n  案例对比：")
    print(f"  {'指标':<20} {'v1':<20} {'v2':<20}")
    print(
        f"  {'总耗时':<20} {fmt_secs(v1c.get('total_e2e')):<20} {fmt_secs(v2c.get('total_e2e')):<20}"
    )
    print(f"  {'首token延迟':<20} {fmt_secs(v1c.get('ttft')):<20} {fmt_secs(v2c.get('ttft')):<20}")
    print(
        f"  {'工具调用次数':<20} {v1c.get('tool_call_count', 'N/A'):<20} {v2c.get('tool_call_count', 'N/A'):<20}"
    )
    print(
        f"  {'工具序列':<20} {str(v1c.get('tool_call_sequence', [])):<20} {str(v2c.get('tool_call_sequence', [])):<20}"
    )
    print(
        f"  {'触发action_confirm':<20} {v1c.get('action_confirm_count', 0):<20} {v2c.get('action_confirm_count', 0):<20}"
    )
    print()

    # 写 JSON
    out_file = Path(out_path)
    out_file.write_text(json.dumps(all_results, ensure_ascii=False, indent=2, default=str))
    print(f"原始数据写入: {out_file}")


def main() -> None:
    parser = argparse.ArgumentParser(description="多轮 Agent benchmark + 案例对比")
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--out", type=str, default="bench_multiturn.json")
    args = parser.parse_args()
    run_benchmark(args.port, args.rounds, args.out)


if __name__ == "__main__":
    main()
