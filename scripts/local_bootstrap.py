from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from packages.storage.db import Base, engine, session_scope
from packages.storage.models import Paper, TopicSubscription, PaperTopic, AnalysisReport


def main() -> None:
    # 直接创建所有表（不使用迁移，避免 Alembic 错误）
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)

    # 验证表是否创建成功
    with session_scope() as session:
        # 检查表是否存在
        from sqlalchemy import inspect

        inspector = inspect(engine)
        tables = inspector.get_table_names()

        print(f"Tables created: {tables}")

        # 如果没有表，手动创建
        if not tables:
            print("Warning: No tables created, trying alternative method...")
            Base.metadata.create_all(bind=engine, checkfirst=False)

        # 再次检查
        tables = inspector.get_table_names()
        print(f"Final tables: {tables}")

        if "papers" in tables:
            print("✅ Database tables created successfully!")
        else:
            print("❌ Failed to create tables!")
            # 打印所有模型
            print("Models to create:", list(Base.metadata.tables.keys()))

    print("SQLite schema initialized.")


if __name__ == "__main__":
    main()
