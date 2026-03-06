"""
IEEE 客户端单元测试

测试 IEEE Xplore API 客户端的各项功能

运行方式:
    pytest tests/test_ieee_client.py -v
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import date

from packages.integrations.ieee_client import IeeeClient, create_ieee_client
from packages.domain.schemas import PaperCreate


class TestIeeeClientInit:
    """测试 IEEE 客户端初始化"""

    def test_init_with_api_key(self):
        """测试使用 API Key 初始化"""
        client = IeeeClient(api_key="test_key")
        assert client.api_key == "test_key"
        assert client._client is None  # 懒加载

    def test_init_without_api_key(self, monkeypatch):
        """测试无 API Key 时从环境变量读取"""
        # Mock get_settings 返回 None
        with patch("packages.integrations.ieee_client.get_settings") as mock_settings:
            mock_settings.return_value.ieee_api_key = None
            client = IeeeClient()
            assert client.api_key is None

    def test_create_helper_function(self):
        """测试便捷函数"""
        client = create_ieee_client(api_key="test_key")
        assert isinstance(client, IeeeClient)
        assert client.api_key == "test_key"


class TestIeeeClientFetch:
    """测试 IEEE 论文搜索"""

    @pytest.fixture
    def mock_response(self):
        """Mock IEEE API 响应"""
        return {
            "articles": [
                {
                    "article_number": "10185093",
                    "doi": "10.1109/CVPR52729.2023.00001",
                    "title": "Deep Learning for Computer Vision",
                    "abstract": "This paper presents a comprehensive survey...",
                    "publication_date": "2023-06-15",
                    "authors": [{"full_name": "John Smith"}, {"full_name": "Jane Doe"}],
                    "publication_title": "IEEE Conference on Computer Vision",
                    "publisher": "IEEE",
                }
            ]
        }

    def test_fetch_by_keywords_success(self, mock_response):
        """测试关键词搜索成功"""
        with patch.object(IeeeClient, "_get", return_value=mock_response):
            client = IeeeClient(api_key="test_key")
            papers = client.fetch_by_keywords("deep learning", max_results=10)

            assert len(papers) == 1
            assert isinstance(papers[0], PaperCreate)
            assert papers[0].source == "ieee"
            assert papers[0].source_id == "10185093"
            assert papers[0].doi == "10.1109/CVPR52729.2023.00001"
            assert papers[0].title == "Deep Learning for Computer Vision"

    def test_fetch_by_keywords_empty_result(self):
        """测试无结果返回"""
        with patch.object(IeeeClient, "_get", return_value={}):
            client = IeeeClient(api_key="test_key")
            papers = client.fetch_by_keywords("nonexistent topic")
            assert len(papers) == 0

    def test_fetch_by_keywords_no_api_key(self, caplog):
        """测试无 API Key 时的行为"""
        client = IeeeClient(api_key=None)
        papers = client.fetch_by_keywords("test")
        assert len(papers) == 0
        assert "IEEE API Key 未配置" in caplog.text

    def test_fetch_by_keywords_with_year_filter(self, mock_response):
        """测试年份过滤"""
        with patch.object(IeeeClient, "_get", return_value=mock_response) as mock_get:
            client = IeeeClient(api_key="test_key")
            client.fetch_by_keywords(
                "deep learning",
                max_results=10,
                start_year=2023,
                end_year=2024,
            )

            # 验证参数传递
            call_args = mock_get.call_args[0][1]
            assert call_args["start_year"] == 2023
            assert call_args["end_year"] == 2024


class TestIeeeClientParse:
    """测试 IEEE 论文解析"""

    def test_parse_complete_article(self):
        """测试解析完整的 IEEE 论文"""
        article = {
            "article_number": "10185093",
            "doi": "10.1109/CVPR.2023.00001",
            "title": "Test Paper",
            "abstract": "Test abstract",
            "publication_date": "2023-06-15",
            "authors": [{"full_name": "Author One"}, {"full_name": "Author Two"}],
            "publication_title": "IEEE Conference",
            "publisher": "IEEE",
            "isbn": "978-1-2345-6789-0",
            "issn": "1234-5678",
        }

        client = IeeeClient(api_key="test_key")
        paper = client._parse_article(article)

        assert paper is not None
        assert paper.source == "ieee"
        assert paper.source_id == "10185093"
        assert paper.doi == "10.1109/CVPR.2023.00001"
        assert paper.title == "Test Paper"
        assert paper.abstract == "Test abstract"
        assert paper.publication_date == date(2023, 6, 15)
        assert len(paper.metadata["authors"]) == 2
        assert paper.metadata["isbn"] == "978-1-2345-6789-0"

    def test_parse_article_missing_title(self):
        """测试解析缺少标题的论文"""
        article = {
            "article_number": "10185093",
            "title": "",  # 空标题
        }

        client = IeeeClient(api_key="test_key")
        paper = client._parse_article(article)

        assert paper is None  # 应该返回 None

    def test_parse_article_missing_article_number(self):
        """测试解析缺少 article_number 的论文"""
        article = {
            "doi": "10.1109/CVPR.2023.00001",
            "title": "Test Paper",
        }

        client = IeeeClient(api_key="test_key")
        paper = client._parse_article(article)

        assert paper is None  # 应该返回 None

    def test_parse_article_date_parsing(self):
        """测试日期解析"""
        # 测试完整日期
        article1 = {
            "article_number": "1",
            "title": "Test",
            "publication_date": "2023-06-15",
        }
        client = IeeeClient(api_key="test_key")
        paper1 = client._parse_article(article1)
        assert paper1.publication_date == date(2023, 6, 15)

        # 测试年月格式
        article2 = {
            "article_number": "2",
            "title": "Test",
            "publication_date": "2023-06",
        }
        paper2 = client._parse_article(article2)
        assert paper2.publication_date == date(2023, 6, 1)

        # 测试无效日期
        article3 = {
            "article_number": "3",
            "title": "Test",
            "publication_date": "invalid-date",
        }
        paper3 = client._parse_article(article3)
        assert paper3.publication_date is None


class TestIeeeClientRetry:
    """测试 IEEE 客户端重试机制"""

    def test_retry_on_429(self):
        """测试 429 限流自动重试"""
        with patch.object(IeeeClient, "client") as mock_client:
            # 第一次返回 429，第二次成功
            mock_response_429 = Mock()
            mock_response_429.status_code = 429
            mock_response_429.raise_for_status.side_effect = Exception("429 Too Many Requests")

            mock_response_success = Mock()
            mock_response_success.status_code = 200
            mock_response_success.json.return_value = {"articles": []}

            mock_client.get.side_effect = [mock_response_429, mock_response_success]

            client = IeeeClient(api_key="test_key")
            papers = client.fetch_by_keywords("test")

            # 验证重试了 2 次
            assert mock_client.get.call_count == 2

    def test_retry_exhausted(self):
        """测试重试用尽后返回 None"""
        with patch.object(IeeeClient, "client") as mock_client:
            # 一直返回 429
            mock_response = Mock()
            mock_response.status_code = 429
            mock_response.raise_for_status.side_effect = Exception("429")

            mock_client.get.side_effect = [mock_response] * 4  # 3 次重试

            client = IeeeClient(api_key="test_key")
            papers = client.fetch_by_keywords("test")

            assert len(papers) == 0


class TestIeeeClientDownload:
    """测试 IEEE PDF 下载"""

    def test_download_pdf_not_implemented(self, caplog):
        """测试 PDF 下载返回 None（暂未实现）"""
        client = IeeeClient(api_key="test_key")
        result = client.download_pdf("10185093")

        assert result is None
        assert "IEEE PDF 下载需要机构订阅" in caplog.text


class TestIeeeClientEdgeCases:
    """测试边界情况"""

    def test_fetch_with_special_characters(self):
        """测试特殊字符查询"""
        with patch.object(IeeeClient, "_get", return_value={"articles": []}) as mock_get:
            client = IeeeClient(api_key="test_key")
            client.fetch_by_keywords("C++ programming")

            # 验证查询参数正确传递
            call_args = mock_get.call_args[0][1]
            assert call_args["querytext"] == "C++ programming"

    def test_fetch_max_results_limit(self):
        """测试最大结果数限制"""
        with patch.object(IeeeClient, "_get", return_value={"articles": []}) as mock_get:
            client = IeeeClient(api_key="test_key")

            # 超过 200 应该被限制
            client.fetch_by_keywords("test", max_results=500)
            call_args = mock_get.call_args[0][1]
            assert call_args["max_records"] == 200

            # 正常值应该保留
            client.fetch_by_keywords("test", max_results=50)
            call_args = mock_get.call_args[0][1]
            assert call_args["max_records"] == 50


# ========== 集成测试（需要真实 API Key）==========


@pytest.mark.skip(reason="需要真实的 IEEE API Key")
class TestIeeeClientIntegration:
    """IEEE 客户端集成测试（需要 API Key）"""

    @pytest.fixture
    def real_client(self):
        """创建真实客户端（需要设置 IEEE_API_KEY 环境变量）"""
        import os

        api_key = os.getenv("IEEE_API_KEY")
        if not api_key:
            pytest.skip("IEEE_API_KEY 未设置")
        return IeeeClient(api_key=api_key)

    def test_real_fetch_by_keywords(self, real_client):
        """测试真实 API 调用"""
        papers = real_client.fetch_by_keywords("machine learning", max_results=5)
        assert len(papers) <= 5
        assert all(p.source == "ieee" for p in papers)

    def test_real_fetch_by_doi(self, real_client):
        """测试真实 DOI 查询"""
        # 使用一个已知的 IEEE 论文 DOI
        doi = "10.1109/CVPR52729.2023.00001"
        paper = real_client.fetch_by_doi(doi)

        if paper:
            assert paper.doi == doi
            assert paper.source == "ieee"
