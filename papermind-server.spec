# -*- mode: python ; coding: utf-8 -*-
"""
PaperMind Desktop — PyInstaller spec
打包 Python 后端为独立二进制，供 Tauri sidecar 调用。
@author Bamzc
"""
import sys
from pathlib import Path

block_cipher = None
ROOT = Path(SPECPATH)

a = Analysis(
    [str(ROOT / "apps" / "desktop" / "server.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "infra" / "migrations"), "infra/migrations"),
        (str(ROOT / "alembic.ini"), "."),
    ],
    hiddenimports=[
        "apps.api.main",
        "apps.worker.main",
        "packages.config",
        "packages.ai",
        "packages.ai.agent_service",
        "packages.ai.agent_tools",
        "packages.ai.brief_service",
        "packages.ai.daily_runner",
        "packages.ai.graph_service",
        "packages.ai.pipelines",
        "packages.ai.rag_service",
        "packages.ai.task_manager",
        "packages.ai.keyword_service",
        "packages.ai.recommendation_service",
        "packages.ai.reasoning_service",
        "packages.ai.figure_service",
        "packages.ai.writing_service",
        "packages.ai.cost_guard",
        "packages.domain",
        "packages.domain.enums",
        "packages.domain.schemas",
        "packages.integrations",
        "packages.integrations.llm_client",
        "packages.storage",
        "packages.storage.db",
        "packages.storage.models",
        "packages.storage.repositories",
        "uvicorn",
        "uvicorn.logging",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.http.httptools_impl",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "fastapi",
        "starlette",
        "sqlalchemy",
        "sqlalchemy.dialects.sqlite",
        "alembic",
        "apscheduler",
        "apscheduler.schedulers.blocking",
        "apscheduler.triggers.cron",
        "pydantic",
        "pydantic_settings",
        "httpx",
        "dotenv",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PIL", "test", "pytest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="papermind-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
