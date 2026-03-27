"""
API 限流测试

测试覆盖：
1. 验证接口限流
2. 限流解除

注意：合规要求 - 不收集 IP，使用 card_key 作为标识
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch
import sys
import os

# 添加 src 目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


class TestRateLimitLogic:
    """测试限流逻辑"""
    
    def test_rate_limit_allows_within_limit(self):
        """测试在限流范围内允许请求"""
        from main import check_rate_limit, _rate_limit_store, _rate_limit_lock
        
        # 清理测试数据
        with _rate_limit_lock:
            _rate_limit_store.clear()
        
        # 验证接口允许10次/分钟
        identifier = "card:ABC12345"
        path = "/api/validate"
        
        for i in range(10):
            allowed, retry_after = check_rate_limit(identifier, path)
            assert allowed == True, f"第{i+1}次请求应该被允许"
            assert retry_after == 0
        
        # 清理
        with _rate_limit_lock:
            _rate_limit_store.clear()
    
    def test_rate_limit_blocks_over_limit(self):
        """测试超过限流范围拒绝请求"""
        from main import check_rate_limit, _rate_limit_store, _rate_limit_lock
        
        # 清理测试数据
        with _rate_limit_lock:
            _rate_limit_store.clear()
        
        identifier = "card:TEST1234"
        path = "/api/validate"
        
        # 发送10次请求（最大限制）
        for i in range(10):
            check_rate_limit(identifier, path)
        
        # 第11次应该被拒绝
        allowed, retry_after = check_rate_limit(identifier, path)
        assert allowed == False, "超过限制应该被拒绝"
        assert retry_after > 0, "应该返回重试等待时间"
        assert retry_after <= 60, "等待时间应在限流窗口内"
        
        # 清理
        with _rate_limit_lock:
            _rate_limit_store.clear()
    
    def test_rate_limit_different_identifiers(self):
        """测试不同标识独立计数"""
        from main import check_rate_limit, _rate_limit_store, _rate_limit_lock
        
        # 清理测试数据
        with _rate_limit_lock:
            _rate_limit_store.clear()
        
        path = "/api/validate"
        
        # 卡密1发送5次请求
        for i in range(5):
            allowed, _ = check_rate_limit("card:AAA11111", path)
            assert allowed == True
        
        # 卡密2也应该能发送5次请求（独立计数）
        for i in range(5):
            allowed, _ = check_rate_limit("card:BBB22222", path)
            assert allowed == True
        
        # 清理
        with _rate_limit_lock:
            _rate_limit_store.clear()
    
    def test_rate_limit_unlimited_path(self):
        """测试无限流的路径"""
        from main import check_rate_limit, _rate_limit_store, _rate_limit_lock
        
        # 清理测试数据
        with _rate_limit_lock:
            _rate_limit_store.clear()
        
        identifier = "card:TEST9999"
        path = "/api/other"  # 无限流配置
        
        # 无限流的路径应该始终允许
        for i in range(20):
            allowed, retry_after = check_rate_limit(identifier, path)
            assert allowed == True
            assert retry_after == 0
        
        # 清理
        with _rate_limit_lock:
            _rate_limit_store.clear()


class TestRateLimitConfig:
    """测试限流配置"""
    
    def test_rate_limit_config_exists(self):
        """测试限流配置存在"""
        from main import RATE_LIMITS
        
        # 验证接口应该有限流配置
        assert "/api/validate" in RATE_LIMITS
        
        # 验证配置结构
        validate_config = RATE_LIMITS["/api/validate"]
        assert "requests" in validate_config
        assert "window" in validate_config
        assert validate_config["requests"] > 0
        assert validate_config["window"] > 0
    
    def test_no_login_rate_limit_in_middleware(self):
        """测试中间件不对登录接口限流（登录有独立安全机制）"""
        from main import RateLimitMiddleware
        
        # 登录接口应该不在中间件的限流列表中
        assert "/api/admin/login" not in RateLimitMiddleware.RATE_LIMITED_PATHS


class TestComplianceCheck:
    """合规检查测试"""
    
    def test_no_ip_in_identifier(self):
        """测试限流标识不包含 IP"""
        from main import check_rate_limit, _rate_limit_store, _rate_limit_lock
        
        # 清理测试数据
        with _rate_limit_lock:
            _rate_limit_store.clear()
        
        # 使用 card_key 作为标识
        identifier = "card:ABC12345"
        path = "/api/validate"
        
        allowed, _ = check_rate_limit(identifier, path)
        assert allowed == True
        
        # 验证存储的 key 不包含 IP
        with _rate_limit_lock:
            for key in _rate_limit_store.keys():
                # key 应该以 "card:" 开头，而不是 IP 格式
                assert key.startswith("card:") or key.startswith("anonymous:"), f"限流标识不应包含 IP: {key}"
        
        # 清理
        with _rate_limit_lock:
            _rate_limit_store.clear()
