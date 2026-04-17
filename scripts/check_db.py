"""检查数据库表"""
import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), "..", "data", "papermind.db")
db_path = os.path.abspath(db_path)

print(f"Database path: {db_path}")
print(f"Database exists: {os.path.exists(db_path)}")

if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    print("\nTables in database:")
    for t in tables:
        print(f"  - {t[0]}")
    
    # 检查 papers 表
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='papers'")
    papers_table = cursor.fetchone()
    print(f"\npapers table exists: {papers_table is not None}")
    
    conn.close()
