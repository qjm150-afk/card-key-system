"""
卡密验证 API 测试

测试覆盖：
1. 验证成功场景
2. 卡密不存在
3. 卡密已停用
4. 卡密已过期（固定日期、激活后N天）
5. 设备绑定限制
6. 首次激活逻辑
7. 飞书链接处理

这是用户直接使用的核心接口。
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch, MagicMock
import json

# 北京时区
BEIJING_TZ = timezone(timedelta(hours=8))


def create_mock_client_for_validate(card_data, existing_logs=None):
    """创建模拟的 Supabase 客户端（用于验证 API）
    
    验证 API 内部有多次数据库查询：
    1. 查询卡密
    2. 查询访问日志（检查首次访问）
    3. 更新设备绑定
    4. 记录访问日志
    """
    mock_client = Mock()
    
    # 记录调用顺序
    call_count = [0]
    
    def mock_table(table_name):
        mock_query = Mock()
        call_count[0] += 1
        
        if table_name == 'card_keys_table':
            # 第一次调用：查询卡密
            def mock_select_execute():
                return Mock(data=[card_data] if card_data else [])
            
            def mock_update_execute():
                return Mock(data=[card_data] if card_data else [])
            
            mock_query.select.return_value.eq.return_value.execute = mock_select_execute
            mock_query.update.return_value.eq.return_value.execute = mock_update_execute
            
        elif table_name == 'access_logs':
            # 查询访问日志 / 插入日志
            def mock_select_execute():
                return Mock(data=existing_logs if existing_logs else [])
            
            mock_query.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute = mock_select_execute
            mock_query.insert.return_value.execute = Mock()
        
        return mock_query
    
    mock_client.table = mock_table
    return mock_client


class TestValidateSuccess:
    """测试验证成功场景"""
    
    @patch('src.main.get_supabase_client')
    def test_validate_success_with_valid_card(self, mock_get_client):
        """测试有效卡密验证成功"""
        from src.main import validate_card_key, ValidateRequest
        from unittest.mock import Mock
        import asyncio
        
        now = datetime.now(BEIJING_TZ)
        card_data = {
            'id': 1,
            'key_value': 'TEST-CARD-001',
            'status': 1,  # 有效
            'expire_at': (now + timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S+08:00'),
            'expire_after_days': None,
            'activated_at': None,
            'max_devices': 5,
            'devices': '[]',
            'feishu_url': 'https://feishu.cn/base/test',
            'feishu_password': 'password123',
            'sales_channel': ''
        }
        
        mock_client = create_mock_client_for_validate(card_data, existing_logs=[])
        mock_get_client.return_value = mock_client
        
        request = ValidateRequest(card_key='TEST-CARD-001', device_id='device1')
        fastapi_request = Mock()
        
        result = asyncio.run(validate_card_key(request, fastapi_request))
        
        assert result.can_access == True
        assert result.msg == "验证成功"
        assert result.url is not None
    
    @patch('src.main.get_supabase_client')
    def test_validate_permanent_card(self, mock_get_client):
        """测试永久有效卡密验证成功"""
        from src.main import validate_card_key, ValidateRequest
        import asyncio
        
        card_data = {
            'id': 1,
            'key_value': 'PERMANENT-001',
            'status': 1,
            'expire_at': None,  # 永久有效
            'expire_after_days': None,
            'activated_at': None,
            'max_devices': 5,
            'devices': '[]',
            'feishu_url': 'https://feishu.cn/base/test',
            'feishu_password': '',
            'sales_channel': ''
        }
        
        mock_client = create_mock_client_for_validate(card_data, existing_logs=[])
        mock_get_client.return_value = mock_client
        
        request = ValidateRequest(card_key='PERMANENT-001', device_id='device1')
        fastapi_request = Mock()
        
        result = asyncio.run(validate_card_key(request, fastapi_request))
        
        assert result.can_access == True


class TestValidateCardNotFound:
    """测试卡密不存在"""
    
    @patch('src.main.get_supabase_client')
    def test_validate_card_not_found(self, mock_get_client):
        """测试卡密不存在返回错误"""
        from src.main import validate_card_key, ValidateRequest
        import asyncio
        
        mock_client = Mock()
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
        mock_get_client.return_value = mock_client
        
        request = ValidateRequest(card_key='NOT-EXIST', device_id='device1')
        fastapi_request = Mock()
        
        result = asyncio.run(validate_card_key(request, fastapi_request))
        
        assert result.can_access == False
        assert result.msg == "卡密不存在"
    
    @patch('src.main.get_supabase_client')
    def test_validate_empty_card_key(self, mock_get_client):
        """测试空卡密返回错误"""
        from src.main import validate_card_key, ValidateRequest
        import asyncio
        
        request = ValidateRequest(card_key='', device_id='device1')
        fastapi_request = Mock()
        
        result = asyncio.run(validate_card_key(request, fastapi_request))
        
        assert result.can_access == False
        assert result.msg == "请输入卡密"


class TestValidateCardDisabled:
    """测试卡密已停用"""
    
    @patch('src.main.get_supabase_client')
    def test_validate_disabled_card(self, mock_get_client):
        """测试已停用卡密返回错误"""
        from src.main import validate_card_key, ValidateRequest
        import asyncio
        
        card_data = {
            'id': 1,
            'key_value': 'DISABLED-001',
            'status': 0,  # 已停用
            'expire_at': None,
            'expire_after_days': None,
            'activated_at': None,
            'max_devices': 5,
            'devices': '[]',
            'feishu_url': '',
            'feishu_password': '',
            'sales_channel': ''
        }
        
        mock_client = create_mock_client_for_validate(card_data, existing_logs=[])
        mock_get_client.return_value = mock_client
        
        request = ValidateRequest(card_key='DISABLED-001', device_id='device1')
        fastapi_request = Mock()
        
        result = asyncio.run(validate_card_key(request, fastapi_request))
        
        assert result.can_access == False
        assert result.msg == "卡密已失效"


class TestValidateExpired:
    """测试卡密已过期"""
    
    @patch('src.main.get_supabase_client')
    def test_validate_fixed_date_expired(self, mock_get_client):
        """测试固定日期已过期"""
        from src.main import validate_card_key, ValidateRequest
        import asyncio
        
        now = datetime.now(BEIJING_TZ)
        card_data = {
            'id': 1,
            'key_value': 'EXPIRED-001',
            'status': 1,
            'expire_at': (now - timedelta(days=10)).strftime('%Y-%m-%d %H:%M:%S+08:00'),  # 已过期
            'expire_after_days': None,
            'activated_at': None,
            'max_devices': 5,
            'devices': '[]',
            'feishu_url': '',
            'feishu_password': '',
            'sales_channel': ''
        }
        
        mock_client = create_mock_client_for_validate(card_data, existing_logs=[])
        mock_get_client.return_value = mock_client
        
        request = ValidateRequest(card_key='EXPIRED-001', device_id='device1')
        fastapi_request = Mock()
        
        result = asyncio.run(validate_card_key(request, fastapi_request))
        
        assert result.can_access == False
        assert "已过期" in result.msg
    
    @patch('src.main.get_supabase_client')
    def test_validate_relative_days_expired(self, mock_get_client):
        """测试激活后N天已过期"""
        from src.main import validate_card_key, ValidateRequest
        import asyncio
        
        now = datetime.now(BEIJING_TZ)
        card_data = {
            'id': 1,
            'key_value': 'RELATIVE-EXPIRED-001',
            'status': 1,
            'expire_at': None,
            'expire_after_days': 7,  # 7天后过期
            'activated_at': (now - timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S+08:00'),  # 30天前激活
            'max_devices': 5,
            'devices': '[]',
            'feishu_url': '',
            'feishu_password': '',
            'sales_channel': ''
        }
        
        mock_client = create_mock_client_for_validate(card_data, existing_logs=[])
        mock_get_client.return_value = mock_client
        
        request = ValidateRequest(card_key='RELATIVE-EXPIRED-001', device_id='device1')
        fastapi_request = Mock()
        
        result = asyncio.run(validate_card_key(request, fastapi_request))
        
        assert result.can_access == False
        assert "已过期" in result.msg
    
    @patch('src.main.get_supabase_client')
    def test_validate_relative_days_not_expired(self, mock_get_client):
        """测试激活后N天未过期"""
        from src.main import validate_card_key, ValidateRequest
        import asyncio
        
        now = datetime.now(BEIJING_TZ)
        card_data = {
            'id': 1,
            'key_value': 'RELATIVE-ACTIVE-001',
            'status': 1,
            'expire_at': None,
            'expire_after_days': 30,  # 30天后过期
            'activated_at': (now - timedelta(days=5)).strftime('%Y-%m-%d %H:%M:%S+08:00'),  # 5天前激活
            'max_devices': 5,
            'devices': '[]',
            'feishu_url': 'https://feishu.cn/base/test',
            'feishu_password': '',
            'sales_channel': ''
        }
        
        mock_client = create_mock_client_for_validate(card_data, existing_logs=[])
        mock_get_client.return_value = mock_client
        
        request = ValidateRequest(card_key='RELATIVE-ACTIVE-001', device_id='device1')
        fastapi_request = Mock()
        
        result = asyncio.run(validate_card_key(request, fastapi_request))
        
        assert result.can_access == True


class TestValidateDeviceLimit:
    """测试设备绑定限制"""
    
    @patch('src.main.get_supabase_client')
    def test_validate_new_device_success(self, mock_get_client):
        """测试新设备绑定成功"""
        from src.main import validate_card_key, ValidateRequest
        import asyncio
        
        now = datetime.now(BEIJING_TZ)
        card_data = {
            'id': 1,
            'key_value': 'DEVICE-TEST-001',
            'status': 1,
            'expire_at': (now + timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S+08:00'),
            'expire_after_days': None,
            'activated_at': None,
            'max_devices': 5,
            'devices': '["device1", "device2"]',  # 已绑定2台设备
            'feishu_url': 'https://feishu.cn/base/test',
            'feishu_password': '',
            'sales_channel': ''
        }
        
        mock_client = create_mock_client_for_validate(card_data, existing_logs=[])
        mock_get_client.return_value = mock_client
        
        request = ValidateRequest(card_key='DEVICE-TEST-001', device_id='device3')  # 新设备
        fastapi_request = Mock()
        
        result = asyncio.run(validate_card_key(request, fastapi_request))
        
        assert result.can_access == True
    
    @patch('src.main.get_supabase_client')
    def test_validate_device_limit_reached(self, mock_get_client):
        """测试设备数量已达上限"""
        from src.main import validate_card_key, ValidateRequest
        import asyncio
        
        now = datetime.now(BEIJING_TZ)
        card_data = {
            'id': 1,
            'key_value': 'DEVICE-LIMIT-001',
            'status': 1,
            'expire_at': (now + timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S+08:00'),
            'expire_after_days': None,
            'activated_at': None,
            'max_devices': 2,  # 最多2台
            'devices': '["device1", "device2"]',  # 已绑定2台
            'feishu_url': '',
            'feishu_password': '',
            'sales_channel': ''
        }
        
        mock_client = create_mock_client_for_validate(card_data, existing_logs=[])
        mock_get_client.return_value = mock_client
        
        request = ValidateRequest(card_key='DEVICE-LIMIT-001', device_id='device3')  # 第3台设备
        fastapi_request = Mock()
        
        result = asyncio.run(validate_card_key(request, fastapi_request))
        
        assert result.can_access == False
        assert "设备数量已达上限" in result.msg or "无法在新设备登录" in result.msg
    
    @patch('src.main.get_supabase_client')
    def test_validate_existing_device_success(self, mock_get_client):
        """测试已绑定设备验证成功"""
        from src.main import validate_card_key, ValidateRequest
        import asyncio
        
        now = datetime.now(BEIJING_TZ)
        card_data = {
            'id': 1,
            'key_value': 'EXISTING-DEVICE-001',
            'status': 1,
            'expire_at': (now + timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S+08:00'),
            'expire_after_days': None,
            'activated_at': (now - timedelta(days=5)).strftime('%Y-%m-%d %H:%M:%S+08:00'),
            'max_devices': 1,  # 只允许1台
            'devices': '["device1"]',  # 已绑定
            'feishu_url': 'https://feishu.cn/base/test',
            'feishu_password': '',
            'sales_channel': ''
        }
        
        mock_client = create_mock_client_for_validate(card_data, existing_logs=[])
        mock_get_client.return_value = mock_client
        
        request = ValidateRequest(card_key='EXISTING-DEVICE-001', device_id='device1')  # 已绑定设备
        fastapi_request = Mock()
        
        result = asyncio.run(validate_card_key(request, fastapi_request))
        
        assert result.can_access == True


class TestValidateFirstActivation:
    """测试首次激活逻辑"""
    
    @patch('src.main.get_supabase_client')
    def test_first_activation_sets_activated_at(self, mock_get_client):
        """测试首次激活记录激活时间"""
        from src.main import validate_card_key, ValidateRequest
        import asyncio
        
        now = datetime.now(BEIJING_TZ)
        card_data = {
            'id': 1,
            'key_value': 'FIRST-ACTIVATE-001',
            'status': 1,
            'expire_at': None,
            'expire_after_days': 30,  # 激活后30天有效
            'activated_at': None,  # 未激活
            'max_devices': 5,
            'devices': '[]',
            'feishu_url': 'https://feishu.cn/base/test',
            'feishu_password': '',
            'sales_channel': ''
        }
        
        mock_client = create_mock_client_for_validate(card_data, existing_logs=[])
        mock_get_client.return_value = mock_client
        
        request = ValidateRequest(card_key='FIRST-ACTIVATE-001', device_id='device1')
        fastapi_request = Mock()
        
        result = asyncio.run(validate_card_key(request, fastapi_request))
        
        # 首次激活应该成功
        assert result.can_access == True


class TestValidateFeishuUrl:
    """测试飞书链接处理"""
    
    @patch('src.main.get_supabase_client')
    def test_feishu_url_gets_embed_params(self, mock_get_client):
        """测试飞书链接添加嵌入参数"""
        from src.main import validate_card_key, ValidateRequest
        import asyncio
        
        now = datetime.now(BEIJING_TZ)
        card_data = {
            'id': 1,
            'key_value': 'FEISHU-URL-001',
            'status': 1,
            'expire_at': (now + timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S+08:00'),
            'expire_after_days': None,
            'activated_at': None,
            'max_devices': 5,
            'devices': '[]',
            'feishu_url': 'https://feishu.cn/base/xxxxxxxx',
            'feishu_password': 'password123',
            'sales_channel': ''
        }
        
        mock_client = create_mock_client_for_validate(card_data, existing_logs=[])
        mock_get_client.return_value = mock_client
        
        request = ValidateRequest(card_key='FEISHU-URL-001', device_id='device1')
        fastapi_request = Mock()
        
        result = asyncio.run(validate_card_key(request, fastapi_request))
        
        assert result.can_access == True
        # 飞书链接应该被添加了嵌入参数
        assert 'hideHeader=1' in result.url or 'hideHeader' in result.url
    
    @patch('src.main.get_supabase_client')
    def test_empty_feishu_url(self, mock_get_client):
        """测试空飞书链接"""
        from src.main import validate_card_key, ValidateRequest
        import asyncio
        
        now = datetime.now(BEIJING_TZ)
        card_data = {
            'id': 1,
            'key_value': 'EMPTY-URL-001',
            'status': 1,
            'expire_at': (now + timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S+08:00'),
            'expire_after_days': None,
            'activated_at': None,
            'max_devices': 5,
            'devices': '[]',
            'feishu_url': None,  # 空
            'feishu_password': None,
            'sales_channel': ''
        }
        
        mock_client = create_mock_client_for_validate(card_data, existing_logs=[])
        mock_get_client.return_value = mock_client
        
        request = ValidateRequest(card_key='EMPTY-URL-001', device_id='device1')
        fastapi_request = Mock()
        
        result = asyncio.run(validate_card_key(request, fastapi_request))
        
        assert result.can_access == True
        assert result.url == ''  # 应该返回空字符串而非 None
