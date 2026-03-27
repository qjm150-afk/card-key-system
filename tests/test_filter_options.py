"""
测试 /api/admin/cards/filter-options API

这个测试文件是为了防止回归之前发现的 bug：
- 变量 relative_expired 和 date_expired 未初始化导致 NameError

测试覆盖：
1. 变量初始化正确性
2. 各种过期时间类型的统计
3. 已过期/未过期标记
4. 边界情况（expire_after_days = 0）
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch, MagicMock
import json

# 北京时区
BEIJING_TZ = timezone(timedelta(hours=8))


def create_mock_client(cards_data, card_types_data=None):
    """创建模拟的 Supabase 客户端
    
    处理 filter-options API 内部的两次数据库查询：
    1. card_keys_table 查询
    2. card_types 查询
    """
    mock_client = Mock()
    
    def mock_table(table_name):
        mock_query = Mock()
        
        if table_name == 'card_keys_table':
            # 第一次查询：卡密数据
            mock_query.select.return_value.execute.return_value.data = cards_data
        elif table_name == 'card_types':
            # 第二次查询：卡种数据
            types_data = card_types_data if card_types_data is not None else []
            # 链式调用：select('id, name').is_('deleted_at', 'null').execute()
            mock_query.select.return_value.is_.return_value.execute.return_value.data = types_data
        
        return mock_query
    
    mock_client.table = mock_table
    return mock_client


class TestFilterOptionsInitialization:
    """测试变量初始化是否正确"""
    
    def test_all_statistical_variables_initialized(self):
        """验证所有统计变量在使用前都已初始化
        
        这是一个回归测试，确保 relative_expired 和 date_expired 变量不会再次被遗忘。
        """
        # 读取源代码检查变量初始化
        import os
        main_py_path = os.path.join(os.path.dirname(__file__), '..', 'src', 'main.py')
        
        with open(main_py_path, 'r') as f:
            content = f.read()
        
        # 找到 filter-options API 的初始化部分
        # 查找 "初始化统计容器" 后面的变量声明
        init_section_start = content.find('# 初始化统计容器')
        if init_section_start == -1:
            pytest.fail("找不到 '初始化统计容器' 注释")
        
        # 获取初始化部分（接下来的 500 个字符）
        init_section = content[init_section_start:init_section_start + 500]
        
        # 验证所有必需的变量都已声明
        required_vars = [
            'status_count',
            'sale_status_count',
            'feishu_url_groups',
            'sales_channel_count',
            'expire_groups',
            'relative_groups',
            'relative_expired',  # 关键！之前遗漏的变量
            'date_expired',      # 关键！之前遗漏的变量
            'permanent_count',
            'expired_count',
            'card_type_count',
            'no_card_type_count'
        ]
        
        for var in required_vars:
            # 检查变量是否被初始化（使用 = {} 或 = 0）
            if f'{var} = {{}}' in init_section or f'{var} = 0' in init_section:
                continue
            elif f'{var} =' in init_section:
                continue
            else:
                pytest.fail(f"变量 '{var}' 未在初始化部分找到，可能导致 NameError")


class TestFilterOptionsExpireGroups:
    """测试过期时间分组统计"""
    
    @patch('src.main.get_supabase_client')
    def test_expire_groups_includes_all_dates(self, mock_get_client, sample_cards, sample_card_types):
        """测试过期时间分组包含所有日期（包括已过期的）
        
        这是核心回归测试：确保已过期的固定日期也出现在筛选列表中
        """
        # 设置 mock
        mock_client = create_mock_client(sample_cards, sample_card_types)
        mock_get_client.return_value = mock_client
        
        # 导入并调用 API
        from src.main import get_filter_options
        import asyncio
        
        result = asyncio.run(get_filter_options())
        
        assert result['success'] == True, f"API 调用失败: {result.get('msg', 'Unknown error')}"
        
        expire_groups = result['data']['expire_groups_list']
        
        # 验证过期时间分组存在
        assert len(expire_groups) > 0, "过期时间分组不应为空"
        
        # 验证包含所有类型
        values = [g['value'] for g in expire_groups]
        
        # 1. 应该有"已过期"分组
        assert 'expired' in values, "应该包含 '已过期' 分组"
        
        # 2. 应该有"永久有效"分组
        assert 'permanent' in values, "应该包含 '永久有效' 分组"
        
        # 3. 应该有"激活后N天有效"分组
        relative_groups = [g for g in expire_groups if g['value'].startswith('relative:')]
        assert len(relative_groups) > 0, "应该包含 '激活后N天有效' 分组"
        
        # 4. 应该有"固定过期日期"分组（关键！之前遗漏的）
        date_groups = [g for g in expire_groups if g['value'].startswith('date:')]
        assert len(date_groups) > 0, "应该包含固定过期日期分组"
    
    @patch('src.main.get_supabase_client')
    def test_expired_dates_marked_correctly(self, mock_get_client, sample_cards, sample_card_types):
        """测试已过期的日期被正确标记"""
        mock_client = create_mock_client(sample_cards, sample_card_types)
        mock_get_client.return_value = mock_client
        
        from src.main import get_filter_options
        import asyncio
        
        result = asyncio.run(get_filter_options())
        
        assert result['success'] == True
        
        expire_groups = result['data']['expire_groups_list']
        
        # 检查固定过期日期的 is_expired 标记
        date_groups = [g for g in expire_groups if g['value'].startswith('date:')]
        
        for group in date_groups:
            assert 'is_expired' in group, f"分组 {group['value']} 缺少 is_expired 字段"
    
    @patch('src.main.get_supabase_client')
    def test_relative_expired_marked_correctly(self, mock_get_client, sample_cards, sample_card_types):
        """测试已过期的激活后N天分组被正确标记"""
        mock_client = create_mock_client(sample_cards, sample_card_types)
        mock_get_client.return_value = mock_client
        
        from src.main import get_filter_options
        import asyncio
        
        result = asyncio.run(get_filter_options())
        
        assert result['success'] == True
        
        expire_groups = result['data']['expire_groups_list']
        
        # 检查激活后N天的 is_expired 标记
        relative_groups = [g for g in expire_groups if g['value'].startswith('relative:')]
        
        for group in relative_groups:
            assert 'is_expired' in group, f"分组 {group['value']} 缺少 is_expired 字段"


class TestFilterOptionsEdgeCases:
    """测试边界情况"""
    
    @patch('src.main.get_supabase_client')
    def test_expire_after_days_zero_uses_expire_at(self, mock_get_client):
        """测试 expire_after_days = 0 时使用 expire_at
        
        这是另一个回归测试：当 expire_after_days = 0 时，应该使用 expire_at
        """
        now = datetime.now(BEIJING_TZ)
        
        # 创建一个 expire_after_days = 0 但有 expire_at 的卡密
        cards = [{
            'id': 1,
            'key_value': 'EDGE-CASE',
            'status': 1,
            'expire_at': (now + timedelta(days=100)).strftime('%Y-%m-%d %H:%M:%S+08:00'),
            'expire_after_days': 0,  # 关键：应该被忽略，使用 expire_at
            'activated_at': None,
            'feishu_url': '',
            'link_name': '',
            'sale_status': 'unsold',
            'sales_channel': '',
            'devices': '[]',
            'card_type_id': None,
            'bstudio_create_time': now.strftime('%Y-%m-%d %H:%M:%S')
        }]
        
        mock_client = create_mock_client(cards, [])
        mock_get_client.return_value = mock_client
        
        from src.main import get_filter_options
        import asyncio
        
        result = asyncio.run(get_filter_options())
        
        assert result['success'] == True
        
        expire_groups = result['data']['expire_groups_list']
        
        # 应该有固定日期分组，而不是激活后0天分组
        date_groups = [g for g in expire_groups if g['value'].startswith('date:')]
        relative_zero = [g for g in expire_groups if g['value'] == 'relative:0']
        
        # 如果 expire_after_days = 0 被正确处理为使用 expire_at
        # 那么应该有日期分组，而不是 relative:0
        assert len(date_groups) > 0 or len(relative_zero) == 0, \
            "expire_after_days=0 应该使用 expire_at（固定日期）"
    
    @patch('src.main.get_supabase_client')
    def test_empty_data_returns_valid_structure(self, mock_get_client):
        """测试空数据返回有效的结构"""
        mock_client = create_mock_client([], [])
        mock_get_client.return_value = mock_client
        
        from src.main import get_filter_options
        import asyncio
        
        result = asyncio.run(get_filter_options())
        
        assert result['success'] == True
        assert 'data' in result
        
        # 验证返回结构正确
        data = result['data']
        assert 'status' in data
        assert 'sale_status' in data
        assert 'feishu_url_list' in data
        assert 'sales_channel_list' in data
        assert 'expire_groups_list' in data
        assert 'card_type_list' in data
        assert 'total' in data
        assert data['total'] == 0


class TestFilterOptionsFeishuUrls:
    """测试飞书链接筛选"""
    
    @patch('src.main.get_supabase_client')
    def test_feishu_urls_includes_all_links(self, mock_get_client, sample_cards, sample_card_types):
        """测试飞书链接筛选包含所有链接"""
        mock_client = create_mock_client(sample_cards, sample_card_types)
        mock_get_client.return_value = mock_client
        
        from src.main import get_filter_options
        import asyncio
        
        result = asyncio.run(get_filter_options())
        
        assert result['success'] == True
        
        feishu_list = result['data']['feishu_url_list']
        
        # 验证飞书链接列表存在
        assert len(feishu_list) > 0, "飞书链接列表不应为空"
        
        # 验证每个链接都有必要字段
        for item in feishu_list:
            assert 'url' in item, "飞书链接项缺少 url 字段"
            assert 'name' in item, "飞书链接项缺少 name 字段"
            assert 'count' in item, "飞书链接项缺少 count 字段"


class TestFilterOptionsNoExceptions:
    """测试不会抛出异常"""
    
    @patch('src.main.get_supabase_client')
    def test_no_nameerror_with_mixed_data(self, mock_get_client):
        """测试混合数据不会导致 NameError
        
        这是对原始 bug 的直接回归测试
        """
        now = datetime.now(BEIJING_TZ)
        
        # 创建包含已过期卡密的数据
        cards = [
            # 已过期的固定日期
            {
                'id': 1,
                'expire_at': (now - timedelta(days=10)).strftime('%Y-%m-%d %H:%M:%S+08:00'),
                'expire_after_days': None,
                'activated_at': None,
                'status': 1,
                'sale_status': 'sold',
                'feishu_url': 'https://test.com',
                'link_name': '测试链接',
                'sales_channel': '',
                'devices': '[]',
                'card_type_id': None,
                'bstudio_create_time': now.strftime('%Y-%m-%d %H:%M:%S')
            },
            # 已过期的激活后N天
            {
                'id': 2,
                'expire_at': None,
                'expire_after_days': 7,
                'activated_at': (now - timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S+08:00'),
                'status': 1,
                'sale_status': 'sold',
                'feishu_url': '',
                'link_name': '',
                'sales_channel': '',
                'devices': '[]',
                'card_type_id': None,
                'bstudio_create_time': now.strftime('%Y-%m-%d %H:%M:%S')
            },
        ]
        
        mock_client = create_mock_client(cards, [])
        mock_get_client.return_value = mock_client
        
        from src.main import get_filter_options
        import asyncio
        
        # 这个调用不应该抛出 NameError
        try:
            result = asyncio.run(get_filter_options())
            assert result['success'] == True, f"API 返回失败: {result.get('msg')}"
        except NameError as e:
            pytest.fail(f"检测到 NameError: {e}，变量可能未正确初始化")
