"""
测试论文导入功能
@author Color2333
"""

import os
import sys

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

import logging
logging.basicConfig(level=logging.DEBUG)

from packages.ai.pipelines import PaperPipelines

def test_ingest():
    """测试论文导入"""
    print("Initializing PaperPipelines...")
    pipelines = PaperPipelines()
    
    print("Testing ArXiv search...")
    try:
        count, inserted_ids, new_count = pipelines.ingest_arxiv(
            query="NeRF",
            max_results=5,
            sort_by="submittedDate",
            days_back=365,
        )
        print(f"Success! Count: {count}, Inserted: {len(inserted_ids)}, New: {new_count}")
        print(f"Inserted IDs: {inserted_ids}")
    except Exception as e:
        print(f"Error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_ingest()
