#!/usr/bin/env python3
"""
IEEE 集成 - 快速验证脚本
不需要 IEEE API Key，只验证数据模型和代码结构

使用方法:
    python3 scripts/verify_ieee_setup.py

@author Color2333
"""

import sys
import os
from datetime import date

print("=" * 70)
print("IEEE 渠道集成 - 快速验证（不需要 API Key）")
print("=" * 70)

# 测试 1: 导入模块
print("\n[1/6] 检查模块导入...")
try:
    from packages.domain.schemas import PaperCreate
    from packages.integrations import ArxivChannel, IeeeChannel
    from packages.integrations.ieee_client import IeeeClient
    print("✅ 模块导入成功")
except ImportError as e:
    print(f"❌ 模块导入失败：{e}")
    sys.exit(1)

# 测试 2: 数据模型验证
print("\n[2/6] 检查数据模型...")
try:
    paper = PaperCreate(
        source="ieee",
        source_id="10185093",
        doi="10.1109/CVPR52729.2023.00001",
        arxiv_id=None,
        title="Test IEEE Paper",
        abstract="Test abstract",
        publication_date=date(2023, 6, 15),
        metadata={}
    )
    assert paper.source == "ieee"
    assert paper.source_id == "10185093"
    assert paper.doi is not None
    print("✅ PaperCreate 模型验证通过")
except Exception as e:
    import traceback
    traceback.print_exc()
    print(f"❌ 数据模型验证失败：{e}")
    sys.exit(1)

# 测试 3: 渠道抽象
print("\n[3/6] 检查渠道抽象...")
try:
    arxiv = ArxivChannel()
    assert arxiv.name == "arxiv"
    print(f"  - ArXiv 渠道：{arxiv.name}")
    
    ieee = IeeeChannel(api_key=None)  # 不传 API Key，使用环境变量
    assert ieee.name == "ieee"
    print(f"  - IEEE 渠道：{ieee.name}")
    print("✅ 渠道抽象验证通过")
except Exception as e:
    import traceback
    traceback.print_exc()
    print(f"❌ 渠道抽象验证失败：{e}")
    sys.exit(1)

# 测试 4: IEEE 客户端初始化
print("\n[4/6] 检查 IEEE 客户端...")
try:
    client = IeeeClient(api_key=None)
    assert client.api_key is None
    print("  - IEEE 客户端初始化成功（无 API Key）")
    print("  - 注意：没有 API Key 时无法执行真实搜索")
    print("✅ IEEE 客户端验证通过")
except Exception as e:
    import traceback
    traceback.print_exc()
    print(f"❌ IEEE 客户端验证失败：{e}")
    sys.exit(1)

# 测试 5: 数据库模型
print("\n[5/6] 检查数据库模型...")
try:
    from packages.storage.models import Paper, TopicSubscription
    from packages.storage.repositories import IeeeQuotaRepository
    
    # 检查 Paper 模型字段
    assert hasattr(Paper, 'source')
    assert hasattr(Paper, 'source_id')
    assert hasattr(Paper, 'doi')
    print("  - Paper 模型：source, source_id, doi 字段存在")
    
    # 检查 TopicSubscription 模型字段
    assert hasattr(TopicSubscription, 'sources')
    assert hasattr(TopicSubscription, 'ieee_daily_quota')
    assert hasattr(TopicSubscription, 'ieee_api_key_override')
    print("  - TopicSubscription 模型：sources, ieee_daily_quota 字段存在")
    
    print("✅ 数据库模型验证通过")
except Exception as e:
    import traceback
    traceback.print_exc()
    print(f"❌ 数据库模型验证失败：{e}")
    sys.exit(1)

# 测试 6: 环境变量检查
print("\n[6/6] 检查环境配置...")
try:
    ieee_key = os.getenv("IEEE_API_KEY")
    
    if ieee_key:
        print(f"  - IEEE_API_KEY: 已配置 ({ieee_key[:10]}...)")
        print("  ✅ 可以执行真实 IEEE 摄取")
    else:
        print(f"  - IEEE_API_KEY: 未配置")
        print("  ⚠️  无法执行真实 IEEE 摄取")
        print("  💡 提示：在 .env 中设置 IEEE_API_KEY=your_key")
    
    print("✅ 环境配置检查完成")
except Exception as e:
    import traceback
    traceback.print_exc()
    print(f"❌ 环境配置检查失败：{e}")

# 总结
print("\n" + "=" * 70)
print("验证完成！")
print("=" * 70)
print("\n✅ 代码结构完整，可以正常使用")
print("\n后续步骤:")
if not ieee_key:
    print("1. 在 .env 中设置 IEEE_API_KEY")
    print("   获取地址：https://developer.ieee.org/")
    print("2. 运行数据库迁移：cd infra && alembic upgrade head")
    print("3. 测试 IEEE 摄取：curl -X POST http://localhost:8000/papers/ingest/ieee?query=test")
else:
    print("1. 运行数据库迁移：cd infra && alembic upgrade head")
    print("2. 测试 IEEE 摄取：curl -X POST http://localhost:8000/papers/ingest/ieee?query=test")

print("\n" + "=" * 70)
