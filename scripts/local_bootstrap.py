"""
数据库初始化脚本
确保在 Docker 容器内正确创建所有表
@author Color2333

使用方法：
    python scripts/local_bootstrap.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    print("=" * 50)
    print("PaperMind 数据库初始化")
    print("=" * 50)

    # 强制使用容器内路径（避免环境变量冲突）
    import os

    os.environ["DATABASE_URL"] = "sqlite:////app/data/papermind.db"

    # 导入数据库引擎
    print("\n[1/4] 导入数据库模块...")
    from packages.storage.db import engine

    # 导入所有模型（关键！不导入不会创建表）
    print("[2/4] 导入所有模型...")
    from packages.storage.models import (
        Base,
        Paper,
        AnalysisReport,
        ImageAnalysis,
        Citation,
        PipelineRun,
        PromptTrace,
        SourceCheckpoint,
        TopicSubscription,
        PaperTopic,
        LLMProviderConfig,
        GeneratedContent,
        CollectionAction,
        ActionPaper,
        EmailConfig,
        DailyReportConfig,
    )

    # 创建所有表
    print("[3/4] 创建数据库表...")
    Base.metadata.create_all(bind=engine)

    # 验证表是否创建成功
    print("[4/4] 验证表...")
    from sqlalchemy import inspect

    inspector = inspect(engine)
    tables = sorted(inspector.get_table_names())

    print(f"\n创建了 {len(tables)} 个表:")
    for t in tables:
        print(f"  - {t}")

    # 检查关键表
    required_tables = ["papers", "topic_subscriptions", "analysis_reports"]
    missing = [t for t in required_tables if t not in tables]

    if missing:
        print(f"\n❌ 错误：缺少必要的表: {missing}")
        sys.exit(1)
    else:
        print("\n✅ 数据库初始化成功！")

    print("=" * 50)


if __name__ == "__main__":
    main()
