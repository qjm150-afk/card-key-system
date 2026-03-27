"""
测试 /api/admin/expire-groups API

这个测试文件是为了确保 expire-groups API 的变量初始化正确，
与 filter-options API 保持一致的逻辑。
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

BEIJING_TZ = timezone(timedelta(hours=8))


class TestExpireGroupsInitialization:
    """测试变量初始化是否正确"""
    
    def test_all_statistical_variables_initialized(self):
        """验证所有统计变量在使用前都已初始化"""
        import os
        main_py_path = os.path.join(os.path.dirname(__file__), '..', 'src', 'main.py')
        
        with open(main_py_path, 'r') as f:
            content = f.read()
        
        # 找到 expire-groups API 的初始化部分
        # 查找 API 函数定义
        api_start = content.find('@app.get("/api/admin/expire-groups")')
        if api_start == -1:
            pytest.fail("找不到 expire-groups API 定义")
        
        # 获取 API 代码部分
        api_section = content[api_start:api_start + 3000]
        
        # 验证所有必需的变量都已声明
        required_vars = [
            'permanent_count',
            'expired_count',
            'expire_groups',
            'relative_groups',
            'relative_expired',
            'date_expired',
        ]
        
        for var in required_vars:
            # 检查变量是否被初始化
            if f'{var} = {{}}' in api_section or f'{var} = 0' in api_section:
                continue
            elif f'{var} =' in api_section:
                continue
            else:
                pytest.fail(f"变量 '{var}' 未在 expire-groups API 中初始化")


class TestExpireGroupsLogic:
    """测试过期时间分组逻辑"""
    
    @patch('src.main.get_supabase_client')
    def test_returns_valid_structure(self, mock_get_client):
        """测试返回有效的数据结构"""
        mock_client = Mock()
        mock_client.table.return_value.select.return_value.execute.return_value.data = []
        mock_get_client.return_value = mock_client
        
        from src.main import get_expire_groups
        import asyncio
        
        result = asyncio.run(get_expire_groups())
        
        assert result['success'] == True
        assert 'data' in result
        assert isinstance(result['data'], list)
    
    @patch('src.main.get_supabase_client')
    def test_includes_all_expire_types(self, mock_get_client, sample_cards):
        """测试包含所有过期类型"""
        mock_client = Mock()
        mock_client.table.return_value.select.return_value.execute.return_value.data = sample_cards
        mock_get_client.return_value = mock_client
        
        from src.main import get_expire_groups
        import asyncio
        
        result = asyncio.run(get_expire_groups())
        
        assert result['success'] == True
        
        groups = result['data']
        types = [g['type'] for g in groups]
        
        # 应该包含所有类型
        assert 'expired' in types, "应该包含已过期类型"
        assert 'relative' in types, "应该包含激活后N天类型"
        assert 'date' in types, "应该包含固定日期类型"
        assert 'permanent' in types, "应该包含永久有效类型"
    
    @patch('src.main.get_supabase_client')
    def test_expired_marked_correctly(self, mock_get_client):
        """测试已过期标记正确"""
        now = datetime.now(BEIJING_TZ)
        
        cards = [
            # 已过期的固定日期
            {
                'expire_at': (now - timedelta(days=10)).strftime('%Y-%m-%d %H:%M:%S+08:00'),
                'expire_after_days': None,
                'activated_at': None,
            },
            # 未过期的固定日期
            {
                'expire_at': (now + timedelta(days=10)).strftime('%Y-%m-%d %H:%M:%S+08:00'),
                'expire_after_days': None,
                'activated_at': None,
            },
            # 已过期的激活后N天
            {
                'expire_at': None,
                'expire_after_days': 7,
                'activated_at': (now - timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S+08:00'),
            },
        ]
        
        mock_client = Mock()
        mock_client.table.return_value.select.return_value.execute.return_value.data = cards
        mock_get_client.return_value = mock_client
        
        from src.main import get_expire_groups
        import asyncio
        
        result = asyncio.run(get_expire_groups())
        
        assert result['success'] == True
        
        groups = result['data']
        
        # 检查 is_expired 字段
        for group in groups:
            assert 'is_expired' in group, f"分组 {group} 缺少 is_expired 字段"


class TestExpireGroupsEdgeCases:
    """测试边界情况"""
    
    @patch('src.main.get_supabase_client')
    def test_expire_after_days_zero_uses_expire_at(self, mock_get_client):
        """测试 expire_after_days = 0 时使用 expire_at"""
        now = datetime.now(BEIJING_TZ)
        
        cards = [{
            'expire_at': (now + timedelta(days=100)).strftime('%Y-%m-%d %H:%M:%S+08:00'),
            'expire_after_days': 0,
            'activated_at': None,
        }]
        
        mock_client = Mock()
        mock_client.table.return_value.select.return_value.execute.return_value.data = cards
        mock_get_client.return_value = mock_client
        
        from src.main import get_expire_groups
        import asyncio
        
        result = asyncio.run(get_expire_groups())
        
        assert result['success'] == True
        
        groups = result['data']
        
        # 应该有日期类型，而不是激活后0天
        date_groups = [g for g in groups if g['type'] == 'date']
        relative_zero = [g for g in groups if g.get('days') == 0]
        
        assert len(date_groups) > 0 or len(relative_zero) == 0, \
            "expire_after_days=0 应该使用 expire_at"
    
    @patch('src.main.get_supabase_client')
    def test_no_exception_with_expired_cards(self, mock_get_client):
        """测试已过期卡密不会导致异常"""
        now = datetime.now(BEIJING_TZ)
        
        cards = [
            # 已过期的固定日期
            {
                'expire_at': (now - timedelta(days=100)).strftime('%Y-%m-%d %H:%M:%S+08:00'),
                'expire_after_days': None,
                'activated_at': None,
            },
            # 已过期的激活后N天
            {
                'expire_at': None,
                'expire_after_days': 1,
                'activated_at': (now - timedelta(days=10)).strftime('%Y-%m-%d %H:%M:%S+08:00'),
            },
        ]
        
        mock_client = Mock()
        mock_client.table.return_value.select.return_value.execute.return_value.data = cards
        mock_get_client.return_value = mock_client
        
        from src.main import get_expire_groups
        import asyncio
        
        # 不应该抛出任何异常
        try:
            result = asyncio.run(get_expire_groups())
            assert result['success'] == True
        except NameError as e:
            pytest.fail(f"检测到 NameError: {e}，变量可能未正确初始化")
        except Exception as e:
            pytest.fail(f"检测到异常: {e}")
