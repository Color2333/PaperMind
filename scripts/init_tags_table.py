"""
初始化标签表
@author Color2333
"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine, text  # noqa: E402

from packages.storage.db import get_database_url  # noqa: E402


def init_tags_table():
    """初始化标签表"""
    engine = create_engine(get_database_url())

    with engine.connect() as conn:
        # 检查 tags 表是否存在
        result = conn.execute(
            text("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='tags'
        """)
        )
        tags_exists = result.fetchone() is not None

        if not tags_exists:
            print("创建 tags 表...")
            conn.execute(
                text("""
                CREATE TABLE tags (
                    id VARCHAR(36) PRIMARY KEY NOT NULL,
                    name VARCHAR(64) NOT NULL UNIQUE,
                    color VARCHAR(32) NOT NULL DEFAULT '#3b82f6',
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            )
            conn.execute(text("CREATE INDEX ix_tags_name ON tags(name)"))
            print("tags 表创建成功")
        else:
            print("tags 表已存在")

        # 检查 paper_tags 表是否存在
        result = conn.execute(
            text("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='paper_tags'
        """)
        )
        paper_tags_exists = result.fetchone() is not None

        if not paper_tags_exists:
            print("创建 paper_tags 表...")
            conn.execute(
                text("""
                CREATE TABLE paper_tags (
                    id VARCHAR(36) PRIMARY KEY NOT NULL,
                    paper_id VARCHAR(36) NOT NULL,
                    tag_id VARCHAR(36) NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE,
                    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE,
                    UNIQUE(paper_id, tag_id)
                )
            """)
            )
            conn.execute(text("CREATE INDEX ix_paper_tags_paper_id ON paper_tags(paper_id)"))
            conn.execute(text("CREATE INDEX ix_paper_tags_tag_id ON paper_tags(tag_id)"))
            print("paper_tags 表创建成功")
        else:
            print("paper_tags 表已存在")

        conn.commit()
        print("\n标签表初始化完成！")


if __name__ == "__main__":
    init_tags_table()
