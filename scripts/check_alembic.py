"""检查 alembic 版本"""
import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), "..", "data", "papermind.db")
db_path = os.path.abspath(db_path)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# 检查 alembic_version
cursor.execute("SELECT version_num FROM alembic_version")
version = cursor.fetchone()
print(f"Current alembic version: {version[0] if version else 'None'}")

# 列出所有迁移文件
migrations_dir = os.path.join(os.path.dirname(__file__), "..", "infra", "migrations", "versions")
if os.path.exists(migrations_dir):
    print("\nMigration files:")
    for f in sorted(os.listdir(migrations_dir)):
        if f.endswith(".py"):
            print(f"  - {f}")

conn.close()
