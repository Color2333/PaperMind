"""
filesystem — 文件系统工具 handlers，参考 learn-claude-code s02
read / write / edit / glob / grep
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _safe_resolve(path: str | Path, workdir: Path) -> Path:
    """解析路径并确保不超出 workdir（防止 path traversal）"""
    resolved = (workdir / path).resolve()
    if not str(resolved).startswith(str(workdir.resolve())):
        raise ValueError(f"Path escapes workspace: {path}")
    return resolved


def run_read(path: str, workdir: str | None = None, limit: int | None = None) -> str:
    """
    读取文件内容。
    可选 limit 参数限制行数（只返回前 N 行）。
    """
    workdir_path = Path(workdir) if workdir else Path.cwd()

    try:
        file_path = _safe_resolve(path, workdir_path)
        lines = file_path.read_text(encoding="utf-8").splitlines()

        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]

        return "\n".join(lines)
    except FileNotFoundError:
        return f"Error: File not found: {path}"
    except Exception as exc:  # noqa: BLE001
        return f"Error: {type(exc).__name__}: {exc}"


def run_write(path: str, content: str, workdir: str | None = None) -> str:
    """
    写入文件内容（覆盖）。
    自动创建父目录。
    """
    workdir_path = Path(workdir) if workdir else Path.cwd()

    try:
        file_path = _safe_resolve(path, workdir_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as exc:  # noqa: BLE001
        return f"Error: {type(exc).__name__}: {exc}"


def run_edit(
    path: str,
    old_text: str,
    new_text: str,
    workdir: str | None = None,
) -> str:
    """
    编辑文件（替换 old_text → new_text，只替换第一个匹配项）。
    如果 old_text 不存在，返回错误。
    """
    workdir_path = Path(workdir) if workdir else Path.cwd()

    try:
        file_path = _safe_resolve(path, workdir_path)
        content = file_path.read_text(encoding="utf-8")

        if old_text not in content:
            return f"Error: Text not found in {path}"

        new_content = content.replace(old_text, new_text, 1)
        file_path.write_text(new_content, encoding="utf-8")
        return f"Edited {path}"
    except FileNotFoundError:
        return f"Error: File not found: {path}"
    except Exception as exc:  # noqa: BLE001
        return f"Error: {type(exc).__name__}: {exc}"


def run_glob(pattern: str, workdir: str | None = None) -> str:
    """
    按 glob pattern 搜索文件。
    pattern 示例：'**/*.py', 'src/**/*.ts'
    """
    workdir_path = Path(workdir) if workdir else Path.cwd()

    try:
        matches = list(workdir_path.glob(pattern))
        if not matches:
            return f"No files matching: {pattern}"

        lines = [
            f"{'dir' if m.is_dir() else 'file'}: {m.relative_to(workdir_path)}" for m in matches
        ]
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        return f"Error: {type(exc).__name__}: {exc}"


def run_grep(
    pattern: str,
    workdir: str | None = None,
    include: str | None = None,
    exclude: str | None = None,
    context: int = 0,
) -> str:
    """
    搜索文件内容。
    - pattern: regex 模式
    - include: glob pattern 过滤（如 '*.py'）
    - exclude: glob pattern 排除
    - context: 上下文行数
    """
    workdir_path = Path(workdir) if workdir else Path.cwd()

    try:
        cmd = ["rg", "--json", "-e", pattern, str(workdir_path)]

        if include:
            cmd.extend(["-g", include])
        if exclude:
            cmd.extend(["-g", f"!{exclude}"])
        if context > 0:
            cmd.extend(["-C", str(context)])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )

        if not result.stdout.strip():
            return f"No matches for: {pattern}"

        return result.stdout.strip()
    except FileNotFoundError:
        # rg not installed, fall back to grep
        cmd = ["grep", "-rn", pattern, str(workdir_path)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.stdout.strip() if result.stdout else f"No matches for: {pattern}"
    except Exception as exc:  # noqa: BLE001
        return f"Error: {type(exc).__name__}: {exc}"
