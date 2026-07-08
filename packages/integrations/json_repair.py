"""
LLM 生成 JSON 的修复与解析工具

处理 LLM 输出 JSON 时的常见问题：未转义控制字符、markdown 代码块包裹、
输出中途截断等。所有函数为纯函数，无外部依赖。
@author Color2333
"""

from __future__ import annotations

import json
import re


def sanitize_json_str(s: str) -> str:
    """修复 LLM 生成 JSON 中的常见问题：未转义的换行、制表符等"""
    # 替换字符串值内部的 literal 换行和制表符
    # 在 JSON string 内（引号之间），将 literal \n \r \t 转为转义序列
    result: list[str] = []
    in_str = False
    esc = False
    for ch in s:
        if esc:
            esc = False
            result.append(ch)
            continue
        if ch == "\\" and in_str:
            esc = True
            result.append(ch)
            continue
        if ch == '"':
            in_str = not in_str
            result.append(ch)
            continue
        if in_str:
            if ch == "\n":
                result.append("\\n")
                continue
            if ch == "\r":
                result.append("\\r")
                continue
            if ch == "\t":
                result.append("\\t")
                continue
            # 去掉其他控制字符 (0x00-0x1F)
            if ord(ch) < 0x20:
                continue
        result.append(ch)
    return "".join(result)


def safe_loads(text: str) -> dict | None:
    """json.loads 带净化回退"""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        return json.loads(sanitize_json_str(text))
    except json.JSONDecodeError:
        return None


def _scan(s: str):
    """扫描 JSON 文本，返回 (stack, in_string, escape_next)"""
    in_str = False
    esc = False
    stk: list[str] = []
    for ch in s:
        if esc:
            esc = False
            continue
        if ch == "\\" and in_str:
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch in "{[":
            stk.append(ch)
        elif ch == "}" and stk and stk[-1] == "{" or ch == "]" and stk and stk[-1] == "[":
            stk.pop()
    return stk, in_str, esc


def repair_truncated_json(text: str) -> dict | None:
    """尝试修复被截断的 JSON，补全缺失的括号"""
    closing_map = {"{": "}", "[": "]"}

    stack, in_string, escape_pending = _scan(text)

    if not stack and not in_string:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    # 策略1：直接补全
    closers = "".join(closing_map[b] for b in reversed(stack))
    # 处理各种截断边界
    suffixes: list[str] = []
    if escape_pending:
        # 截断在 \ 后面，去掉尾部 \ 再闭合
        base = text[:-1]
        if in_string:
            suffixes = [f'"{closers}', f'""{closers}']
        else:
            suffixes = [closers]
        for sfx in suffixes:
            try:
                return json.loads(base + sfx)
            except json.JSONDecodeError:
                continue

    # 构造 (base_text, suffix) 候选列表
    attempts: list[tuple[str, str]] = []

    if in_string:
        # 截断在字符串中间，去掉末尾不完整转义
        trimmed = text
        if trimmed.endswith("\\"):
            trimmed = trimmed[:-1]
        elif re.search(r"\\u[0-9a-fA-F]{0,3}$", trimmed):
            trimmed = re.sub(r"\\u[0-9a-fA-F]{0,3}$", "", trimmed)
        attempts = [
            (trimmed, f'"{closers}'),
            (trimmed, f'" {closers}'),
        ]
    else:
        clean = text.rstrip().rstrip(",").rstrip()
        attempts = [
            (text, closers),
            (clean, closers),
            (text, f'""{closers}'),
            (text, f"null{closers}"),
        ]

    for base, sfx in attempts:
        try:
            return json.loads(base + sfx)
        except json.JSONDecodeError:
            continue

    # 策略2：回退到最后一个完整的值边界再闭合
    # 找结构性断点: }, ], "后的逗号, 完整数值等
    candidates: list[int] = []
    for m in re.finditer(r"[}\]]\s*,", text):
        candidates.append(m.start() + 1)
    for m in re.finditer(r'"\s*,', text):
        candidates.append(m.start() + 1)
    for m in re.finditer(r"[}\]]\s*$", text):
        candidates.append(m.start() + 1)

    for pos in sorted(set(candidates), reverse=True):
        chunk = text[:pos].rstrip().rstrip(",")
        stk2, in_s2, _ = _scan(chunk)
        if in_s2:
            continue
        cl = "".join(closing_map[b] for b in reversed(stk2))
        try:
            return json.loads(chunk + cl)
        except json.JSONDecodeError:
            continue

    return None


def try_parse_json(text: str) -> dict | None:
    """从文本中尽力提取 JSON 对象，处理 markdown 代码块和截断"""
    raw = text.strip()
    if not raw:
        return None

    # 1. 直接解析（含净化回退）
    r = safe_loads(raw)
    if r is not None:
        return r

    # 2. 去除 markdown 代码块
    fence_match = re.search(
        r"```(?:json)?\s*\n?(.*?)```",
        raw,
        re.DOTALL,
    )
    if fence_match:
        r = safe_loads(fence_match.group(1).strip())
        if r is not None:
            return r

    # 3. 提取 {} 块
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end > start:
        r = safe_loads(raw[start : end + 1])
        if r is not None:
            return r

    # 4. 截断 JSON 修复：模型可能在输出中途停止
    if start != -1:
        candidate = sanitize_json_str(raw[start:])
        repaired = repair_truncated_json(candidate)
        if repaired is not None:
            return repaired

    return None
