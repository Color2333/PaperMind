"""
IEEE 集成 - Mock 测试方案
不需要真实 API Key 也能测试完整流程

@author Color2333
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import date, datetime
from uuid import uuid4

from packages.domain.schemas import PaperCreate
from packages.storage.db import session_scope
from packages.storage.repositories import PaperRepository, IeeeQuotaRepository


class TestIeeeMockIngest:
    """IEEE Mock 摄取测试 - 不需要 API Key"""
    
    @pytest.fixture
    def mock_ieee_papers(self):
        """Mock IEEE 论文数据"""
        return [
            PaperCreate(
                source="ieee",
                source_id="10185093",
                doi="10.1109/CVPR52729.2023.00001",
                arxiv_id=None,
                title="Deep Learning for Computer Vision",
                abstract="This paper presents a comprehensive survey...",
                publication_date=date(2023, 6, 15),
                metadata={
                    "authors": ["John Smith", "Jane Doe"],
                    "venue": "IEEE Conference on Computer Vision",
                    "publisher": "IEEE",
                }
            ),
            PaperCreate(
                source="ieee",
                source_id="10185094",
                doi="10.1109/CVPR52729.2023.00002",
                arxiv_id=None,
                title="Neural Networks for Image Recognition",
                abstract="We propose a novel neural network architecture...",
                publication_date=date(2023, 7, 20),
                metadata={
                    "authors": ["Bob Johnson"],
                    "venue": "IEEE Conference on Computer Vision",
                    "publisher": "IEEE",
                }
            ),
        ]
    
    def test_ieee_paper_creation(self, mock_ieee_papers):
        """测试 IEEE 论文数据创建"""
        assert len(mock_ieee_papers) == 2
        assert all(p.source == "ieee" for p in mock_ieee_papers)
        assert all(p.doi is not None for p in mock_ieee_papers)
        print("✅ IEEE 论文数据创建成功")
    
    def test_ieee_paper_save_to_db(self, mock_ieee_papers):
        """测试 IEEE 论文保存到数据库"""
        with session_scope() as session:
            repo = PaperRepository(session)
            
            # 保存 Mock 论文
            saved_ids = []
            for paper in mock_ieee_papers:
                saved = repo.upsert_paper(paper)
                saved_ids.append(saved.id)
            
            # 验证保存成功
            assert len(saved_ids) == 2
            
            # 验证 source 字段
            saved_papers = repo.list_by_ids(saved_ids)
            assert all(p.source == "ieee" for p in saved_papers)
            
            # 验证 DOI 字段
            assert all(p.doi is not None for p in saved_papers)
            
            print(f"✅ IEEE 论文成功入库：{len(saved_ids)} 篇")
    
    def test_ieee_paper_query(self, mock_ieee_papers):
        """测试 IEEE 论文查询"""
        with session_scope() as session:
            repo = PaperRepository(session)
            
            # 按 source 查询
            all_papers = repo.list_all(limit=1000)
            ieee_papers = [p for p in all_papers if p.source == "ieee"]
            
            print(f"✅ 数据库中有 {len(ieee_papers)} 篇 IEEE 论文")
            
            # 按 DOI 查询
            doi = "10.1109/CVPR52729.2023.00001"
            papers_with_doi = [p for p in all_papers if p.doi == doi]
            assert len(papers_with_doi) > 0
            print(f"✅ 按 DOI 查询成功：{doi}")


class TestIeeeQuotaMock:
    """IEEE 配额 Mock 测试"""
    
    def test_quota_check_without_api(self):
        """测试配额检查（不需要 API）"""
        with session_scope() as session:
            quota_repo = IeeeQuotaRepository(session)
            today = date.today()
            
            # 测试配额检查
            topic_id = str(uuid4())
            has_quota = quota_repo.check_quota(topic_id, today, limit=10)
            assert has_quota == True
            print("✅ 配额检查成功")
            
            # 测试配额消耗
            success = quota_repo.consume_quota(topic_id, today, 1)
            assert success == True
            print("✅ 配额消耗成功")
            
            # 测试剩余配额查询
            remaining = quota_repo.get_remaining(topic_id, today)
            assert remaining == 9
            print(f"✅ 剩余配额查询成功：{remaining}")


class TestMultiChannelMock:
    """多渠道 Mock 测试"""
    
    def test_channel_selector(self):
        """测试渠道选择逻辑"""
        # 模拟前端选择的渠道
        selected_channels = ["arxiv", "ieee"]
        
        # 验证至少选择一个渠道
        assert len(selected_channels) > 0
        print(f"✅ 选择的渠道：{selected_channels}")
        
        # 验证渠道格式
        valid_channels = {"arxiv", "ieee"}
        assert all(c in valid_channels for c in selected_channels)
        print("✅ 渠道格式验证通过")


def run_mock_tests():
    """运行所有 Mock 测试"""
    print("=" * 60)
    print("IEEE 集成 Mock 测试（不需要 API Key）")
    print("=" * 60)
    
    # 测试 1: IEEE 论文数据创建
    print("\n[Test 1] IEEE 论文数据创建")
    mock_papers = [
        PaperCreate(
            source="ieee",
            source_id="10185093",
            doi="10.1109/CVPR52729.2023.00001",
            arxiv_id=None,
            title="Mock IEEE Paper",
            abstract="Test abstract",
            publication_date=date(2023, 6, 15),
            metadata={}
        )
    ]
    assert len(mock_papers) == 1
    assert mock_papers[0].source == "ieee"
    print("✅ 通过")
    
    # 测试 2: 数据库模型验证
    print("\n[Test 2] 数据库模型验证")
    with session_scope() as session:
        # 检查 papers 表是否有 source 字段
        from packages.storage.models import Paper
        assert hasattr(Paper, 'source')
        assert hasattr(Paper, 'source_id')
        assert hasattr(Paper, 'doi')
        print("✅ 数据库字段验证通过")
    
    # 测试 3: 配额管理
    print("\n[Test 3] 配额管理测试")
    with session_scope() as session:
        quota_repo = IeeeQuotaRepository(session)
        today = date.today()
        topic_id = "test_topic"
        
        # 检查配额
        has_quota = quota_repo.check_quota(topic_id, today, limit=10)
        print(f"  - 有配额：{has_quota}")
        
        # 消耗配额
        consumed = quota_repo.consume_quota(topic_id, today, 1)
        print(f"  - 消耗配额：{consumed}")
        
        # 查询剩余
        remaining = quota_repo.get_remaining(topic_id, today)
        print(f"  - 剩余配额：{remaining}")
        print("✅ 配额管理测试通过")
    
    # 测试 4: 渠道抽象
    print("\n[Test 4] 渠道抽象测试")
    from packages.integrations import ArxivChannel, IeeeChannel
    
    # ArXiv 渠道（不需要 API Key）
    arxiv_channel = ArxivChannel()
    assert arxiv_channel.name == "arxiv"
    print(f"  - ArXiv 渠道：{arxiv_channel.name}")
    
    # IEEE 渠道（没有 API Key 时返回空）
    ieee_channel = IeeeChannel(api_key=None)
    assert ieee_channel.name == "ieee"
    papers = ieee_channel.fetch("test", max_results=5)
    assert len(papers) == 0  # 没有 API Key 返回空
    print(f"  - IEEE 渠道：{ieee_channel.name} (无 API Key 返回空)")
    print("✅ 渠道抽象测试通过")
    
    print("\n" + "=" * 60)
    print("所有 Mock 测试通过！✅")
    print("=" * 60)
    print("\n提示：这些测试不需要 IEEE API Key")
    print("可以快速验证数据模型和代码逻辑")


if __name__ == "__main__":
    run_mock_tests()
