"""
Pytest 配置和共享 fixtures
"""
import pytest
import sys
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch, MagicMock

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# 北京时区
BEIJING_TZ = timezone(timedelta(hours=8))


@pytest.fixture
def mock_supabase_client():
    """模拟 Supabase 客户端"""
    client = Mock()
    return client


@pytest.fixture
def sample_cards():
    """示例卡密数据 - 包含各种过期类型"""
    now = datetime.now(BEIJING_TZ)
    
    return [
        # 1. 永久有效
        {
            'id': 1,
            'key_value': 'PERMANENT-001',
            'status': 1,
            'expire_at': None,
            'expire_after_days': None,
            'activated_at': None,
            'feishu_url': 'https://feishu.cn/doc1',
            'link_name': '链接A',
            'sale_status': 'unsold',
            'sales_channel': '',
            'devices': '[]',
            'card_type_id': 1,
            'bstudio_create_time': (now - timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')
        },
        # 2. 固定过期日期 - 未过期
        {
            'id': 2,
            'key_value': 'FIXED-FUTURE-001',
            'status': 1,
            'expire_at': (now + timedelta(days=365)).strftime('%Y-%m-%d %H:%M:%S+08:00'),
            'expire_after_days': None,
            'activated_at': None,
            'feishu_url': 'https://feishu.cn/doc2',
            'link_name': '链接B',
            'sale_status': 'sold',
            'sales_channel': '小红书',
            'devices': '[]',
            'card_type_id': 1,
            'bstudio_create_time': (now - timedelta(days=20)).strftime('%Y-%m-%d %H:%M:%S')
        },
        # 3. 固定过期日期 - 已过期
        {
            'id': 3,
            'key_value': 'FIXED-EXPIRED-001',
            'status': 1,
            'expire_at': (now - timedelta(days=10)).strftime('%Y-%m-%d %H:%M:%S+08:00'),
            'expire_after_days': None,
            'activated_at': None,
            'feishu_url': 'https://feishu.cn/doc3',
            'link_name': '链接C',
            'sale_status': 'sold',
            'sales_channel': '闲鱼',
            'devices': '[]',
            'card_type_id': 2,
            'bstudio_create_time': (now - timedelta(days=60)).strftime('%Y-%m-%d %H:%M:%S')
        },
        # 4. 激活后N天有效 - 已激活未过期
        {
            'id': 4,
            'key_value': 'RELATIVE-ACTIVE-001',
            'status': 1,
            'expire_at': None,
            'expire_after_days': 30,
            'activated_at': (now - timedelta(days=5)).strftime('%Y-%m-%d %H:%M:%S+08:00'),
            'feishu_url': 'https://feishu.cn/doc1',
            'link_name': '链接A',
            'sale_status': 'sold',
            'sales_channel': '小红书',
            'devices': '["device1"]',
            'card_type_id': 1,
            'bstudio_create_time': (now - timedelta(days=10)).strftime('%Y-%m-%d %H:%M:%S')
        },
        # 5. 激活后N天有效 - 已激活已过期
        {
            'id': 5,
            'key_value': 'RELATIVE-EXPIRED-001',
            'status': 1,
            'expire_at': None,
            'expire_after_days': 7,
            'activated_at': (now - timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S+08:00'),
            'feishu_url': 'https://feishu.cn/doc2',
            'link_name': '链接B',
            'sale_status': 'sold',
            'sales_channel': '',
            'devices': '["device2"]',
            'card_type_id': 2,
            'bstudio_create_time': (now - timedelta(days=40)).strftime('%Y-%m-%d %H:%M:%S')
        },
        # 6. 激活后N天有效 - 未激活
        {
            'id': 6,
            'key_value': 'RELATIVE-INACTIVE-001',
            'status': 1,
            'expire_at': None,
            'expire_after_days': 1,
            'activated_at': None,
            'feishu_url': '',
            'link_name': '',
            'sale_status': 'unsold',
            'sales_channel': '',
            'devices': '[]',
            'card_type_id': None,
            'bstudio_create_time': (now - timedelta(days=5)).strftime('%Y-%m-%d %H:%M:%S')
        },
        # 7. 特殊情况：expire_after_days = 0，使用 expire_at
        {
            'id': 7,
            'key_value': 'EDGE-CASE-ZERO-DAYS',
            'status': 1,
            'expire_at': (now + timedelta(days=100)).strftime('%Y-%m-%d %H:%M:%S+08:00'),
            'expire_after_days': 0,  # 应该使用 expire_at
            'activated_at': None,
            'feishu_url': 'https://feishu.cn/doc4',
            'link_name': '链接D',
            'sale_status': 'unsold',
            'sales_channel': '',
            'devices': '[]',
            'card_type_id': 1,
            'bstudio_create_time': (now - timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
        },
    ]


@pytest.fixture
def sample_card_types():
    """示例卡种数据"""
    return [
        {'id': 1, 'name': '卡种A', 'deleted_at': None},
        {'id': 2, 'name': '卡种B', 'deleted_at': None},
    ]
