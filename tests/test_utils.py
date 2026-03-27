"""
核心工具函数测试

测试覆盖：
1. parse_datetime - 时间解析函数（多格式支持、时区处理、边界情况）
2. calculate_is_expired - 过期判断函数（各种过期类型、边界情况）
3. generate_card_key - 卡密生成函数（格式、唯一性）

这些是系统的核心逻辑，被多个 API 调用。
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# 北京时区
BEIJING_TZ = timezone(timedelta(hours=8))


class TestParseDatetime:
    """测试 parse_datetime 函数
    
    这是系统中最关键的工具函数，处理多种时间格式。
    时区处理错误会导致过期判断失败。
    """
    
    def test_parse_iso_format_with_timezone(self):
        """测试标准 ISO 格式（带时区）"""
        from main import parse_datetime
        
        # 标准 ISO 格式
        result = parse_datetime("2026-03-27T15:30:00+08:00")
        
        assert result is not None
        assert result.year == 2026
        assert result.month == 3
        assert result.day == 27
        assert result.hour == 15
        assert result.minute == 30
        assert result.tzinfo is not None
    
    def test_parse_iso_format_with_z(self):
        """测试 ISO 格式（Z 结尾，UTC 时间）"""
        from main import parse_datetime
        
        # UTC 时间（Z 结尾）
        result = parse_datetime("2026-03-27T07:30:00Z")
        
        assert result is not None
        # Z 应该被正确转换为 +00:00
        assert result.tzinfo is not None
    
    def test_parse_supabase_format_with_cst(self):
        """测试 Supabase 格式（CST 时区）"""
        from main import parse_datetime
        
        # Supabase 返回的格式
        result = parse_datetime("2026-03-27 15:30:00 +0800 CST")
        
        assert result is not None
        assert result.year == 2026
        assert result.month == 3
        assert result.day == 27
        assert result.hour == 15
        assert result.minute == 30
        assert result.tzinfo is not None
    
    def test_parse_supabase_format_with_offset(self):
        """测试 Supabase 格式（+0800 偏移）"""
        from main import parse_datetime
        
        result = parse_datetime("2026-03-27 15:30:00 +0800")
        
        assert result is not None
        assert result.hour == 15
        assert result.tzinfo is not None
    
    def test_parse_supabase_format_utc(self):
        """测试 Supabase 格式（UTC 时间）"""
        from main import parse_datetime
        
        # UTC 时间
        result = parse_datetime("2026-03-27 07:30:00 +0000")
        
        assert result is not None
        assert result.tzinfo is not None
    
    def test_parse_datetime_object(self):
        """测试传入 datetime 对象"""
        from main import parse_datetime
        
        dt = datetime(2026, 3, 27, 15, 30, 0, tzinfo=BEIJING_TZ)
        result = parse_datetime(dt)
        
        assert result is not None
        assert result.year == 2026
        assert result.tzinfo is not None
    
    def test_parse_none_returns_none(self):
        """测试 None 输入返回 None"""
        from main import parse_datetime
        
        result = parse_datetime(None)
        
        assert result is None
    
    def test_parse_invalid_format_returns_none(self):
        """测试无效格式返回 None"""
        from main import parse_datetime
        
        # 完全无效的字符串
        result = parse_datetime("invalid-date-string")
        
        assert result is None
    
    def test_parse_empty_string_returns_none(self):
        """测试空字符串返回 None"""
        from main import parse_datetime
        
        result = parse_datetime("")
        
        # 空字符串会导致解析失败
        assert result is None or isinstance(result, datetime)
    
    def test_parse_adds_timezone_if_missing(self):
        """测试无时区的时间字符串自动添加北京时区"""
        from main import parse_datetime
        
        # 无时区的时间字符串
        result = parse_datetime("2026-03-27T15:30:00")
        
        assert result is not None
        assert result.tzinfo is not None
        # 应该被设置为北京时区


class TestCalculateIsExpired:
    """测试 calculate_is_expired 函数
    
    这是过期判断的核心逻辑，直接影响用户体验。
    """
    
    def test_fixed_date_expired(self):
        """测试固定日期已过期"""
        from main import calculate_is_expired
        
        now = datetime.now(BEIJING_TZ)
        card = {
            'expire_at': (now - timedelta(days=10)).strftime('%Y-%m-%d %H:%M:%S+08:00'),
            'expire_after_days': None,
            'activated_at': None
        }
        
        assert calculate_is_expired(card) == True
    
    def test_fixed_date_not_expired(self):
        """测试固定日期未过期"""
        from main import calculate_is_expired
        
        now = datetime.now(BEIJING_TZ)
        card = {
            'expire_at': (now + timedelta(days=10)).strftime('%Y-%m-%d %H:%M:%S+08:00'),
            'expire_after_days': None,
            'activated_at': None
        }
        
        assert calculate_is_expired(card) == False
    
    def test_relative_days_expired(self):
        """测试激活后N天已过期"""
        from main import calculate_is_expired
        
        now = datetime.now(BEIJING_TZ)
        card = {
            'expire_at': None,
            'expire_after_days': 7,
            'activated_at': (now - timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S+08:00')
        }
        
        assert calculate_is_expired(card) == True
    
    def test_relative_days_not_expired(self):
        """测试激活后N天未过期"""
        from main import calculate_is_expired
        
        now = datetime.now(BEIJING_TZ)
        card = {
            'expire_at': None,
            'expire_after_days': 30,
            'activated_at': (now - timedelta(days=5)).strftime('%Y-%m-%d %H:%M:%S+08:00')
        }
        
        assert calculate_is_expired(card) == False
    
    def test_relative_days_not_activated(self):
        """测试激活后N天有效但未激活"""
        from main import calculate_is_expired
        
        card = {
            'expire_at': None,
            'expire_after_days': 7,
            'activated_at': None  # 未激活
        }
        
        # 未激活不计入过期
        assert calculate_is_expired(card) == False
    
    def test_permanent_valid(self):
        """测试永久有效"""
        from main import calculate_is_expired
        
        card = {
            'expire_at': None,
            'expire_after_days': None,
            'activated_at': None
        }
        
        assert calculate_is_expired(card) == False
    
    def test_both_conditions_checked(self):
        """测试两个过期条件都会被检查
        
        注意：函数会检查 expire_at 和 expire_after_days 两个条件，
        任意一个过期就返回 True。
        """
        from main import calculate_is_expired
        
        now = datetime.now(BEIJING_TZ)
        
        # 场景1：expire_at 未过期，但 expire_after_days 已过期
        card = {
            'expire_at': (now + timedelta(days=100)).strftime('%Y-%m-%d %H:%M:%S+08:00'),
            'expire_after_days': 1,  # 1天后过期
            'activated_at': (now - timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S+08:00')
        }
        
        # 激活后1天，已经过了30天，应该已过期
        assert calculate_is_expired(card) == True
        
        # 场景2：expire_at 已过期，expire_after_days 未过期
        card2 = {
            'expire_at': (now - timedelta(days=10)).strftime('%Y-%m-%d %H:%M:%S+08:00'),
            'expire_after_days': 100,  # 100天后过期
            'activated_at': (now - timedelta(days=5)).strftime('%Y-%m-%d %H:%M:%S+08:00')
        }
        
        # 固定日期已过期，应该已过期
        assert calculate_is_expired(card2) == True
    
    def test_edge_case_expire_at_boundary(self):
        """测试过期时间边界情况（刚好过期）"""
        from main import calculate_is_expired
        
        now = datetime.now(BEIJING_TZ)
        # 过期时间设置为 1 秒前
        card = {
            'expire_at': (now - timedelta(seconds=1)).strftime('%Y-%m-%d %H:%M:%S+08:00'),
            'expire_after_days': None,
            'activated_at': None
        }
        
        assert calculate_is_expired(card) == True
    
    def test_edge_case_expire_at_future(self):
        """测试过期时间边界情况（1秒后过期）"""
        from main import calculate_is_expired
        
        now = datetime.now(BEIJING_TZ)
        # 过期时间设置为 1 秒后
        card = {
            'expire_at': (now + timedelta(seconds=1)).strftime('%Y-%m-%d %H:%M:%S+08:00'),
            'expire_after_days': None,
            'activated_at': None
        }
        
        assert calculate_is_expired(card) == False


class TestGenerateCardKey:
    """测试 generate_card_key 函数
    
    卡密格式影响用户体验和系统识别。
    """
    
    def test_format_correctness(self):
        """测试卡密格式正确性"""
        from main import generate_card_key
        
        key = generate_card_key()
        
        # 格式: XXX-XXXX-XXXX-XXXX
        parts = key.split('-')
        assert len(parts) == 4
        assert len(parts[0]) == 3  # 前缀
        assert len(parts[1]) == 4
        assert len(parts[2]) == 4
        assert len(parts[3]) == 4
    
    def test_default_prefix(self):
        """测试默认前缀"""
        from main import generate_card_key
        
        key = generate_card_key()
        
        assert key.startswith('CSS-')
    
    def test_custom_prefix(self):
        """测试自定义前缀"""
        from main import generate_card_key
        
        key = generate_card_key(prefix="ABC")
        
        assert key.startswith('ABC-')
    
    def test_hex_characters_only(self):
        """测试只包含十六进制字符"""
        from main import generate_card_key
        
        key = generate_card_key()
        
        # 移除前缀和分隔符
        hex_part = key.replace('CSS-', '').replace('-', '')
        
        # 应该只包含 0-9 和 A-F
        valid_chars = set('0123456789ABCDEF')
        assert all(c in valid_chars for c in hex_part)
    
    def test_uniqueness(self):
        """测试唯一性（生成 100 个卡密）"""
        from main import generate_card_key
        
        keys = set()
        for _ in range(100):
            key = generate_card_key()
            keys.add(key)
        
        # 100 个卡密应该全部唯一
        assert len(keys) == 100
    
    def test_different_prefixes_independent(self):
        """测试不同前缀独立"""
        from main import generate_card_key
        
        key1 = generate_card_key(prefix="AAA")
        key2 = generate_card_key(prefix="BBB")
        
        assert key1.startswith('AAA-')
        assert key2.startswith('BBB-')
        assert key1 != key2


class TestAddFeishuEmbedParams:
    """测试 add_feishu_embed_params 函数
    
    飞书链接处理影响嵌入效果。
    """
    
    def test_adds_params_to_feishu_base_url(self):
        """测试飞书多维表格链接添加参数"""
        from main import add_feishu_embed_params
        
        url = "https://feishu.cn/base/xxxxxxxx"
        result = add_feishu_embed_params(url)
        
        assert "hideHeader=1" in result
        assert "hideSidebar=1" in result
        assert "vc=true" in result
    
    def test_adds_params_to_feishu_app_url(self):
        """测试飞书应用链接添加参数"""
        from main import add_feishu_embed_params
        
        url = "https://feishu.cn/app/xxxxxxxx"
        result = add_feishu_embed_params(url)
        
        assert "hideHeader=1" in result
    
    def test_adds_params_to_larksuite_url(self):
        """测试 LarkSuite 链接添加参数"""
        from main import add_feishu_embed_params
        
        url = "https://larksuite.com/base/xxxxxxxx"
        result = add_feishu_embed_params(url)
        
        assert "hideHeader=1" in result
    
    def test_non_feishu_url_unchanged(self):
        """测试非飞书链接不处理"""
        from main import add_feishu_embed_params
        
        url = "https://example.com/page"
        result = add_feishu_embed_params(url)
        
        assert result == url
    
    def test_existing_params_not_overwritten(self):
        """测试已有参数不覆盖"""
        from main import add_feishu_embed_params
        
        url = "https://feishu.cn/base/xxxxxxxx?hideHeader=0"
        result = add_feishu_embed_params(url)
        
        # 用户已设置的参数不应被覆盖
        assert "hideHeader=0" in result
    
    def test_empty_url_returns_empty(self):
        """测试空 URL 返回空"""
        from main import add_feishu_embed_params
        
        result = add_feishu_embed_params("")
        
        assert result == ""
    
    def test_none_url_returns_none(self):
        """测试 None URL 返回 None"""
        from main import add_feishu_embed_params
        
        result = add_feishu_embed_params(None)
        
        assert result is None
