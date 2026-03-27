"""
API 限流测试

测试覆盖：
1. 验证接口限流
2. 登录接口限流
3. 限流解除
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
        identifier = "test_user_1"
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
        
        identifier = "test_user_2"
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
        
        # 用户1发送5次请求
        for i in range(5):
            allowed, _ = check_rate_limit("user_1", path)
            assert allowed == True
        
        # 用户2也应该能发送5次请求（独立计数）
        for i in range(5):
            allowed, _ = check_rate_limit("user_2", path)
            assert allowed == True
        
        # 清理
        with _rate_limit_lock:
            _rate_limit_store.clear()
    
    def test_rate_limit_different_paths(self):
        """测试不同路径独立限流"""
        from main import check_rate_limit, _rate_limit_store, _rate_limit_lock
        
        # 清理测试数据
        with _rate_limit_lock:
            _rate_limit_store.clear()
        
        identifier = "test_user_3"
        
        # 验证接口：10次/分钟
        for i in range(10):
            allowed, _ = check_rate_limit(identifier, "/api/validate")
            assert allowed == True
        
        # 验证接口超限
        allowed, _ = check_rate_limit(identifier, "/api/validate")
        assert allowed == False
        
        # 登录接口应该独立计算（5次/5分钟）
        allowed, _ = check_rate_limit(identifier, "/api/admin/login")
        assert allowed == True, "不同路径应该独立限流"
        
        # 清理
        with _rate_limit_lock:
            _rate_limit_store.clear()
    
    def test_rate_limit_unlimited_path(self):
        """测试无限流的路径"""
        from main import check_rate_limit, _rate_limit_store, _rate_limit_lock
        
        # 清理测试数据
        with _rate_limit_lock:
            _rate_limit_store.clear()
        
        identifier = "test_user_4"
        path = "/api/other"  # 无限流配置
        
        # 无限流的路径应该始终允许
        for i in range(20):
            allowed, retry_after = check_rate_limit(identifier, path)
            assert allowed == True
            assert retry_after == 0
        
        # 清理
        with _rate_limit_lock:
            _rate_limit_store.clear()
    
    def test_rate_limit_login_stricter(self):
        """测试登录接口更严格的限流"""
        from main import check_rate_limit, _rate_limit_store, _rate_limit_lock
        
        # 清理测试数据
        with _rate_limit_lock:
            _rate_limit_store.clear()
        
        identifier = "test_user_5"
        path = "/api/admin/login"
        
        # 登录接口：5次/5分钟
        for i in range(5):
            allowed, _ = check_rate_limit(identifier, path)
            assert allowed == True
        
        # 第6次应该被拒绝
        allowed, retry_after = check_rate_limit(identifier, path)
        assert allowed == False
        assert retry_after > 0
        assert retry_after <= 300  # 5分钟窗口
        
        # 清理
        with _rate_limit_lock:
            _rate_limit_store.clear()


class TestRateLimitConfig:
    """测试限流配置"""
    
    def test_rate_limit_config_exists(self):
        """测试限流配置存在"""
        from main import RATE_LIMITS
        
        assert "/api/validate" in RATE_LIMITS
        assert "/api/admin/login" in RATE_LIMITS
        
        # 验证配置结构
        validate_config = RATE_LIMITS["/api/validate"]
        assert "requests" in validate_config
        assert "window" in validate_config
        assert validate_config["requests"] > 0
        assert validate_config["window"] > 0
        
        # 登录接口应该更严格
        login_config = RATE_LIMITS["/api/admin/login"]
        assert login_config["requests"] <= validate_config["requests"]
        assert login_config["window"] >= validate_config["window"]
