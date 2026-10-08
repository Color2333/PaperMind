"""初始化数据库 - 创建所有必要的表

历史版本手写 13+ 张表的 DDL，与 ORM 模型持续漂移（实证坑：46 列缺失，
papers.favorited 等列的 DEFAULT 形状也不一致，Go apply 直接 409）。
现收敛到官方 schema 路径 packages.storage.db.run_migrations：
- PG：alembic upgrade head（幂等）；
- SQLite：ORM Base.metadata.create_all（只建缺失表）+ 列级 _safe_add_column 兜底。

用法：python scripts/init_db.py（DATABASE_URL 决定目标库）
"""

import os
import sys

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)


def init_database():
    """初始化数据库（官方 schema 路径的唯一入口）"""
    from packages.storage.db import run_migrations

    run_migrations()
    print("\nDatabase initialization completed!")


if __name__ == "__main__":
    init_database()
