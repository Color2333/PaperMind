"""
PaperMind Desktop Server — PyInstaller 入口
Tauri sidecar 调用此二进制，自动选端口 + 内嵌 scheduler。
@author Bamzc
"""
from __future__ import annotations

import json
import logging
import os
import signal
import socket
import sys
import threading
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("papermind.desktop")


def _find_free_port() -> int:
    """获取 OS 分配的空闲端口"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _setup_data_dir(data_dir: Path) -> None:
    """确保数据目录结构完整"""
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "papers").mkdir(exist_ok=True)
    (data_dir / "briefs").mkdir(exist_ok=True)


def _apply_env_overrides(data_dir: Path, env_file: Path | None) -> None:
    """
    根据用户配置的路径注入环境变量，
    让 Pydantic Settings 和 SQLAlchemy 读到正确的值。
    """
    os.environ["DATABASE_URL"] = f"sqlite:///{data_dir / 'papermind.db'}"
    os.environ["PDF_STORAGE_ROOT"] = str(data_dir / "papers")
    os.environ["BRIEF_OUTPUT_ROOT"] = str(data_dir / "briefs")

    if env_file and env_file.is_file():
        os.environ["PAPERMIND_ENV_FILE"] = str(env_file)
        from dotenv import load_dotenv
        load_dotenv(env_file, override=True)
        logger.info("Loaded .env from %s", env_file)


def _start_scheduler() -> None:
    """后台线程运行 APScheduler（复用 worker 逻辑）"""
    from apps.worker.main import run_worker
    t = threading.Thread(target=run_worker, daemon=True, name="scheduler")
    t.start()
    logger.info("Embedded scheduler started on background thread")


def main() -> None:
    data_dir = Path(os.environ.get("PAPERMIND_DATA_DIR", "")).expanduser()
    env_file_str = os.environ.get("PAPERMIND_ENV_FILE", "")
    env_file = Path(env_file_str).expanduser() if env_file_str else None

    if not data_dir or not data_dir.is_absolute():
        data_dir = Path.home() / "Library" / "Application Support" / "PaperMind" / "data"

    _setup_data_dir(data_dir)
    _apply_env_overrides(data_dir, env_file)

    port = _find_free_port()

    os.environ["API_HOST"] = "127.0.0.1"
    os.environ["API_PORT"] = str(port)
    os.environ["CORS_ALLOW_ORIGINS"] = f"tauri://localhost,https://tauri.localhost,http://127.0.0.1:{port}"

    # Tauri 通过 stdout 读取端口号（协议：首行 JSON）
    sys.stdout.write(json.dumps({"port": port}) + "\n")
    sys.stdout.flush()

    logger.info("PaperMind Desktop starting on 127.0.0.1:%d", port)
    logger.info("Data dir: %s", data_dir)

    _start_scheduler()

    import uvicorn
    from apps.api.main import app

    def _handle_signal(sig, _frame):
        logger.info("Received signal %s, shutting down...", sig)
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=port,
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    main()
