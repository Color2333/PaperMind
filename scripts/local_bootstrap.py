import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from packages.storage.db import engine
from packages.storage.models import Base

# 导入所有模型，确保它们被注册到 Base.metadata
print("Importing all models...")
from packages.storage.models import (
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
print("Creating database tables...")
Base.metadata.create_all(bind=engine)

# 验证
print("Checking tables...")
from sqlalchemy import inspect

inspector = inspect(engine)
tables = sorted(inspector.get_table_names())

print(f"Tables created: {tables}")

# 检查关键表
required_tables = ["papers", "topic_subscriptions", "analysis_reports"]
missing = [t for t in required_tables if t not in tables]

if missing:
    print(f"⚠️  Missing tables: {missing}")
else:
    print("✅ All required tables created!")

print("\nSQLite schema initialized.")
