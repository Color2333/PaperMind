"""
初始化数据库 - 创建所有必要的表
@author Color2333
"""

import os
import sys

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from sqlalchemy import create_engine, text
from packages.storage.db import engine


def init_database():
    """初始化数据库"""
    
    with engine.connect() as conn:
        # 检查 papers 表是否存在
        result = conn.execute(text("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='papers'
        """))
        papers_exists = result.fetchone() is not None
        
        if not papers_exists:
            print("Creating papers table...")
            # 创建 papers 表
            conn.execute(text("""
                CREATE TABLE papers (
                    id VARCHAR(36) PRIMARY KEY NOT NULL,
                    title VARCHAR(1024) NOT NULL,
                    arxiv_id VARCHAR(64) NOT NULL UNIQUE,
                    abstract TEXT NOT NULL,
                    pdf_path VARCHAR(1024),
                    publication_date DATE,
                    embedding JSON,
                    read_status VARCHAR(20) NOT NULL DEFAULT 'unread',
                    metadata JSON NOT NULL DEFAULT '{}',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    favorited BOOLEAN NOT NULL DEFAULT 0,
                    metadata_json JSON
                )
            """))
            conn.execute(text("CREATE INDEX ix_papers_arxiv_id ON papers(arxiv_id)"))
            conn.execute(text("CREATE INDEX ix_papers_created_at ON papers(created_at)"))
            conn.execute(text("CREATE INDEX ix_papers_read_status ON papers(read_status)"))
            conn.execute(text("CREATE INDEX ix_papers_favorited ON papers(favorited)"))
            print("papers table created")
        
        # 检查 analysis_reports 表
        result = conn.execute(text("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='analysis_reports'
        """))
        if not result.fetchone():
            print("Creating analysis_reports table...")
            conn.execute(text("""
                CREATE TABLE analysis_reports (
                    id VARCHAR(36) PRIMARY KEY NOT NULL,
                    paper_id VARCHAR(36) NOT NULL,
                    summary_md TEXT,
                    deep_dive_md TEXT,
                    key_insights JSON NOT NULL DEFAULT '{}',
                    skim_score FLOAT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE
                )
            """))
            conn.execute(text("CREATE INDEX ix_analysis_reports_paper_id ON analysis_reports(paper_id)"))
            print("analysis_reports table created")
        
        # 检查 citations 表
        result = conn.execute(text("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='citations'
        """))
        if not result.fetchone():
            print("Creating citations table...")
            conn.execute(text("""
                CREATE TABLE citations (
                    id VARCHAR(36) PRIMARY KEY NOT NULL,
                    source_paper_id VARCHAR(36) NOT NULL,
                    target_paper_id VARCHAR(36) NOT NULL,
                    context TEXT,
                    FOREIGN KEY (source_paper_id) REFERENCES papers(id) ON DELETE CASCADE,
                    FOREIGN KEY (target_paper_id) REFERENCES papers(id) ON DELETE CASCADE,
                    UNIQUE(source_paper_id, target_paper_id)
                )
            """))
            conn.execute(text("CREATE INDEX ix_citations_source_paper_id ON citations(source_paper_id)"))
            conn.execute(text("CREATE INDEX ix_citations_target_paper_id ON citations(target_paper_id)"))
            print("citations table created")
        
        # 检查 pipeline_runs 表
        result = conn.execute(text("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='pipeline_runs'
        """))
        if not result.fetchone():
            print("Creating pipeline_runs table...")
            conn.execute(text("""
                CREATE TABLE pipeline_runs (
                    id VARCHAR(36) PRIMARY KEY NOT NULL,
                    paper_id VARCHAR(36),
                    pipeline_name VARCHAR(100) NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    elapsed_ms INTEGER,
                    error_message TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE SET NULL
                )
            """))
            conn.execute(text("CREATE INDEX ix_pipeline_runs_paper_id ON pipeline_runs(paper_id)"))
            conn.execute(text("CREATE INDEX ix_pipeline_runs_pipeline_name ON pipeline_runs(pipeline_name)"))
            print("pipeline_runs table created")
        
        # 检查 prompt_traces 表
        result = conn.execute(text("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='prompt_traces'
        """))
        if not result.fetchone():
            print("Creating prompt_traces table...")
            conn.execute(text("""
                CREATE TABLE prompt_traces (
                    id VARCHAR(36) PRIMARY KEY NOT NULL,
                    paper_id VARCHAR(36),
                    stage VARCHAR(64) NOT NULL,
                    provider VARCHAR(64) NOT NULL,
                    model VARCHAR(128) NOT NULL,
                    prompt_digest TEXT NOT NULL,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE SET NULL
                )
            """))
            conn.execute(text("CREATE INDEX ix_prompt_traces_paper_id ON prompt_traces(paper_id)"))
            conn.execute(text("CREATE INDEX ix_prompt_traces_stage ON prompt_traces(stage)"))
            conn.execute(text("CREATE INDEX ix_prompt_traces_created_at ON prompt_traces(created_at)"))
            print("prompt_traces table created")
        
        # 检查 source_checkpoints 表
        result = conn.execute(text("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='source_checkpoints'
        """))
        if not result.fetchone():
            print("Creating source_checkpoints table...")
            conn.execute(text("""
                CREATE TABLE source_checkpoints (
                    id VARCHAR(36) PRIMARY KEY NOT NULL,
                    source VARCHAR(64) NOT NULL UNIQUE,
                    last_fetch_at DATETIME,
                    last_published_date DATE,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """))
            print("source_checkpoints table created")
        
        # 检查 topic_subscriptions 表
        result = conn.execute(text("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='topic_subscriptions'
        """))
        if not result.fetchone():
            print("Creating topic_subscriptions table...")
            conn.execute(text("""
                CREATE TABLE topic_subscriptions (
                    id VARCHAR(36) PRIMARY KEY NOT NULL,
                    name VARCHAR(128) NOT NULL,
                    query VARCHAR(512) NOT NULL,
                    enabled BOOLEAN NOT NULL DEFAULT 1,
                    daily_limit INTEGER NOT NULL DEFAULT 10,
                    last_fetch_at DATETIME,
                    last_published_date DATE,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    schedule_frequency VARCHAR(20) NOT NULL DEFAULT 'daily',
                    schedule_time_utc INTEGER NOT NULL DEFAULT 21,
                    enable_date_filter BOOLEAN NOT NULL DEFAULT 0,
                    date_filter_days INTEGER NOT NULL DEFAULT 7
                )
            """))
            print("topic_subscriptions table created")
        
        # 检查 paper_topics 表
        result = conn.execute(text("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='paper_topics'
        """))
        if not result.fetchone():
            print("Creating paper_topics table...")
            conn.execute(text("""
                CREATE TABLE paper_topics (
                    id VARCHAR(36) PRIMARY KEY NOT NULL,
                    paper_id VARCHAR(36) NOT NULL,
                    topic_id VARCHAR(36) NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE,
                    FOREIGN KEY (topic_id) REFERENCES topic_subscriptions(id) ON DELETE CASCADE,
                    UNIQUE(paper_id, topic_id)
                )
            """))
            conn.execute(text("CREATE INDEX ix_paper_topics_paper_id ON paper_topics(paper_id)"))
            conn.execute(text("CREATE INDEX ix_paper_topics_topic_id ON paper_topics(topic_id)"))
            print("paper_topics table created")
        
        # 检查 tags 表
        result = conn.execute(text("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='tags'
        """))
        if not result.fetchone():
            print("Creating tags table...")
            conn.execute(text("""
                CREATE TABLE tags (
                    id VARCHAR(36) PRIMARY KEY NOT NULL,
                    name VARCHAR(64) NOT NULL UNIQUE,
                    color VARCHAR(32) NOT NULL DEFAULT '#3b82f6',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("CREATE INDEX ix_tags_name ON tags(name)"))
            print("tags table created")
        
        # 检查 paper_tags 表
        result = conn.execute(text("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='paper_tags'
        """))
        if not result.fetchone():
            print("Creating paper_tags table...")
            conn.execute(text("""
                CREATE TABLE paper_tags (
                    id VARCHAR(36) PRIMARY KEY NOT NULL,
                    paper_id VARCHAR(36) NOT NULL,
                    tag_id VARCHAR(36) NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE,
                    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE,
                    UNIQUE(paper_id, tag_id)
                )
            """))
            conn.execute(text("CREATE INDEX ix_paper_tags_paper_id ON paper_tags(paper_id)"))
            conn.execute(text("CREATE INDEX ix_paper_tags_tag_id ON paper_tags(tag_id)"))
            print("paper_tags table created")
        
        # 检查 llm_provider_configs 表
        result = conn.execute(text("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='llm_provider_configs'
        """))
        if not result.fetchone():
            print("Creating llm_provider_configs table...")
            conn.execute(text("""
                CREATE TABLE llm_provider_configs (
                    id VARCHAR(36) PRIMARY KEY NOT NULL,
                    provider VARCHAR(64) NOT NULL,
                    name VARCHAR(128) NOT NULL,
                    api_key VARCHAR(512) NOT NULL,
                    base_url VARCHAR(512),
                    model_skim VARCHAR(128),
                    model_deep VARCHAR(128),
                    model_vision VARCHAR(128),
                    model_embedding VARCHAR(128),
                    enabled BOOLEAN NOT NULL DEFAULT 1,
                    priority INTEGER NOT NULL DEFAULT 0,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """))
            print("llm_provider_configs table created")
        
        # 检查 agent_conversations 表
        result = conn.execute(text("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='agent_conversations'
        """))
        if not result.fetchone():
            print("Creating agent_conversations table...")
            conn.execute(text("""
                CREATE TABLE agent_conversations (
                    id VARCHAR(36) PRIMARY KEY NOT NULL,
                    title VARCHAR(512),
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """))
            print("agent_conversations table created")
        
        # 检查 agent_messages 表
        result = conn.execute(text("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='agent_messages'
        """))
        if not result.fetchone():
            print("Creating agent_messages table...")
            conn.execute(text("""
                CREATE TABLE agent_messages (
                    id VARCHAR(36) PRIMARY KEY NOT NULL,
                    conversation_id VARCHAR(36) NOT NULL,
                    role VARCHAR(32) NOT NULL,
                    content TEXT NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (conversation_id) REFERENCES agent_conversations(id) ON DELETE CASCADE
                )
            """))
            conn.execute(text("CREATE INDEX ix_agent_messages_conversation_id ON agent_messages(conversation_id)"))
            print("agent_messages table created")
        
        # 检查 agent_pending_actions 表
        result = conn.execute(text("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='agent_pending_actions'
        """))
        if not result.fetchone():
            print("Creating agent_pending_actions table...")
            conn.execute(text("""
                CREATE TABLE agent_pending_actions (
                    id VARCHAR(36) PRIMARY KEY NOT NULL,
                    conversation_id VARCHAR(36) NOT NULL,
                    action_type VARCHAR(32) NOT NULL,
                    action_data JSON NOT NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'pending',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (conversation_id) REFERENCES agent_conversations(id) ON DELETE CASCADE
                )
            """))
            print("agent_pending_actions table created")
        
        # 检查 cs_categories 表
        result = conn.execute(text("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='cs_categories'
        """))
        if not result.fetchone():
            print("Creating cs_categories table...")
            conn.execute(text("""
                CREATE TABLE cs_categories (
                    id VARCHAR(36) PRIMARY KEY NOT NULL,
                    category_code VARCHAR(32) NOT NULL UNIQUE,
                    category_name VARCHAR(128) NOT NULL,
                    description TEXT,
                    parent_code VARCHAR(32),
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """))
            print("cs_categories table created")
        
        # 检查 cs_feed_subscriptions 表
        result = conn.execute(text("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='cs_feed_subscriptions'
        """))
        if not result.fetchone():
            print("Creating cs_feed_subscriptions table...")
            conn.execute(text("""
                CREATE TABLE cs_feed_subscriptions (
                    id VARCHAR(36) PRIMARY KEY NOT NULL,
                    category_code VARCHAR(32) NOT NULL,
                    daily_limit INTEGER NOT NULL DEFAULT 30,
                    enabled BOOLEAN NOT NULL DEFAULT 1,
                    status VARCHAR(32) NOT NULL DEFAULT 'active',
                    cool_down_until DATETIME,
                    last_run_at DATETIME,
                    last_run_count INTEGER NOT NULL DEFAULT 0,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """))
            print("cs_feed_subscriptions table created")
        
        # 检查 ieee_api_quotas 表
        result = conn.execute(text("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='ieee_api_quotas'
        """))
        if not result.fetchone():
            print("Creating ieee_api_quotas table...")
            conn.execute(text("""
                CREATE TABLE ieee_api_quotas (
                    id VARCHAR(36) PRIMARY KEY NOT NULL,
                    date DATE NOT NULL UNIQUE,
                    request_count INTEGER NOT NULL DEFAULT 0,
                    reset_at DATETIME NOT NULL
                )
            """))
            print("ieee_api_quotas table created")
        
        # 检查 email_configs 表
        result = conn.execute(text("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='email_configs'
        """))
        if not result.fetchone():
            print("Creating email_configs table...")
            conn.execute(text("""
                CREATE TABLE email_configs (
                    id VARCHAR(36) PRIMARY KEY NOT NULL,
                    name VARCHAR(128) NOT NULL,
                    smtp_host VARCHAR(256) NOT NULL,
                    smtp_port INTEGER NOT NULL,
                    smtp_username VARCHAR(256),
                    smtp_password VARCHAR(512),
                    smtp_use_tls BOOLEAN NOT NULL DEFAULT 1,
                    smtp_use_ssl BOOLEAN NOT NULL DEFAULT 0,
                    from_address VARCHAR(256) NOT NULL,
                    to_addresses TEXT NOT NULL,
                    enabled BOOLEAN NOT NULL DEFAULT 1,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """))
            print("email_configs table created")
        
        # 检查 daily_report_configs 表
        result = conn.execute(text("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='daily_report_configs'
        """))
        if not result.fetchone():
            print("Creating daily_report_configs table...")
            conn.execute(text("""
                CREATE TABLE daily_report_configs (
                    id VARCHAR(36) PRIMARY KEY NOT NULL,
                    enabled BOOLEAN NOT NULL DEFAULT 1,
                    email_config_id VARCHAR(36),
                    send_time_utc INTEGER NOT NULL DEFAULT 21,
                    include_skimmed BOOLEAN NOT NULL DEFAULT 1,
                    include_deep_read BOOLEAN NOT NULL DEFAULT 1,
                    include_topics TEXT,
                    cron_expression VARCHAR(64),
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (email_config_id) REFERENCES email_configs(id) ON DELETE SET NULL
                )
            """))
            print("daily_report_configs table created")
        
        # 检查 collection_actions 表
        result = conn.execute(text("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='collection_actions'
        """))
        if not result.fetchone():
            print("Creating collection_actions table...")
            conn.execute(text("""
                CREATE TABLE collection_actions (
                    id VARCHAR(36) PRIMARY KEY NOT NULL,
                    action_type VARCHAR(32) NOT NULL,
                    title VARCHAR(512) NOT NULL,
                    query VARCHAR(1024),
                    topic_id VARCHAR(36),
                    paper_count INTEGER NOT NULL DEFAULT 0,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (topic_id) REFERENCES topic_subscriptions(id) ON DELETE SET NULL
                )
            """))
            conn.execute(text("CREATE INDEX ix_collection_actions_type ON collection_actions(action_type)"))
            conn.execute(text("CREATE INDEX ix_collection_actions_created_at ON collection_actions(created_at)"))
            conn.execute(text("CREATE INDEX ix_collection_actions_topic_id ON collection_actions(topic_id)"))
            print("collection_actions table created")
        
        # 检查 action_papers 表
        result = conn.execute(text("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='action_papers'
        """))
        if not result.fetchone():
            print("Creating action_papers table...")
            conn.execute(text("""
                CREATE TABLE action_papers (
                    id VARCHAR(36) PRIMARY KEY NOT NULL,
                    action_id VARCHAR(36) NOT NULL,
                    paper_id VARCHAR(36) NOT NULL,
                    FOREIGN KEY (action_id) REFERENCES collection_actions(id) ON DELETE CASCADE,
                    FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE,
                    UNIQUE(action_id, paper_id)
                )
            """))
            conn.execute(text("CREATE INDEX ix_action_papers_action_id ON action_papers(action_id)"))
            conn.execute(text("CREATE INDEX ix_action_papers_paper_id ON action_papers(paper_id)"))
            print("action_papers table created")
        
        # 检查 generated_contents 表
        result = conn.execute(text("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='generated_contents'
        """))
        if not result.fetchone():
            print("Creating generated_contents table...")
            conn.execute(text("""
                CREATE TABLE generated_contents (
                    id VARCHAR(36) PRIMARY KEY NOT NULL,
                    content_type VARCHAR(32) NOT NULL,
                    title VARCHAR(512) NOT NULL,
                    keyword VARCHAR(256),
                    paper_id VARCHAR(36),
                    markdown TEXT NOT NULL,
                    metadata_json JSON,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE SET NULL
                )
            """))
            conn.execute(text("CREATE INDEX ix_generated_contents_created_at ON generated_contents(created_at)"))
            conn.execute(text("CREATE INDEX ix_generated_contents_content_type ON generated_contents(content_type)"))
            conn.execute(text("CREATE INDEX ix_generated_contents_paper_id ON generated_contents(paper_id)"))
            print("generated_contents table created")
        
        # 检查 image_analyses 表
        result = conn.execute(text("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='image_analyses'
        """))
        if not result.fetchone():
            print("Creating image_analyses table...")
            conn.execute(text("""
                CREATE TABLE image_analyses (
                    id VARCHAR(36) PRIMARY KEY NOT NULL,
                    paper_id VARCHAR(36) NOT NULL,
                    page_number INTEGER NOT NULL,
                    image_index INTEGER NOT NULL DEFAULT 0,
                    image_type VARCHAR(32) NOT NULL DEFAULT 'figure',
                    caption TEXT,
                    description TEXT NOT NULL DEFAULT '',
                    bbox_json JSON,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE
                )
            """))
            conn.execute(text("CREATE INDEX ix_image_analyses_paper_id ON image_analyses(paper_id)"))
            print("image_analyses table created")
        
        # 检查并添加缺失的列
        # 检查 pipeline_runs 表是否有 decision_note 列
        try:
            result = conn.execute(text("PRAGMA table_info(pipeline_runs)"))
            columns = [row[1] for row in result.fetchall()]
            if "decision_note" not in columns:
                print("Adding decision_note column to pipeline_runs...")
                conn.execute(text("ALTER TABLE pipeline_runs ADD COLUMN decision_note TEXT"))
                print("decision_note column added")
        except Exception as e:
            print(f"Warning: Could not check/add decision_note column: {e}")
        
        # 检查 alembic_version 表并设置版本
        result = conn.execute(text("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='alembic_version'
        """))
        if not result.fetchone():
            print("Creating alembic_version table...")
            conn.execute(text("""
                CREATE TABLE alembic_version (
                    version_num VARCHAR(32) PRIMARY KEY NOT NULL
                )
            """))
            # 设置最新的迁移版本
            conn.execute(text("""
                INSERT INTO alembic_version (version_num) VALUES ('20260415_0001')
            """))
            print("alembic_version table created")
        
        conn.commit()
        print("\nDatabase initialization completed!")


if __name__ == "__main__":
    init_database()
