"""
登录安全测试

测试覆盖：
1. 登录失败计数
2. 账户锁定机制
3. 锁定解除
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch
import sys
import os

# 添加 src 目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


class TestLoginSecurity:
    """测试登录安全功能"""
    
    def test_check_login_lockout_not_locked(self):
        """测试正常 IP 未被锁定"""
        from main import check_login_lockout, _login_lockouts, _rate_limit_lock
        
        # 清理测试数据
        with _rate_limit_lock:
            _login_lockouts.clear()
        
        is_locked, remaining = check_login_lockout("192.168.1.1")
        
        assert is_locked == False
        assert remaining == 0
    
    def test_record_login_failure(self):
        """测试记录登录失败"""
        from main import record_login_failure, _login_failures, _rate_limit_lock
        
        # 清理测试数据
        with _rate_limit_lock:
            _login_failures.clear()
        
        ip = "192.168.1.2"
        
        # 第一次失败
        result = record_login_failure(ip)
        assert result["locked"] == False
        assert result["remaining_attempts"] == 4
        
        # 第二次失败
        result = record_login_failure(ip)
        assert result["locked"] == False
        assert result["remaining_attempts"] == 3
    
    def test_login_lockout_after_max_failures(self):
        """测试达到最大失败次数后锁定"""
        from main import record_login_failure, check_login_lockout, _login_failures, _login_lockouts, _rate_limit_lock
        
        # 清理测试数据
        with _rate_limit_lock:
            _login_failures.clear()
            _login_lockouts.clear()
        
        ip = "192.168.1.3"
        
        # 连续失败 5 次
        for i in range(5):
            result = record_login_failure(ip)
        
        # 第 5 次应该被锁定
        assert result["locked"] == True
        assert result["lockout_until"] is not None
        
        # 检查锁定状态
        is_locked, remaining = check_login_lockout(ip)
        assert is_locked == True
        assert remaining > 0
        
        # 清理
        with _rate_limit_lock:
            _login_failures.clear()
            _login_lockouts.clear()
    
    def test_clear_login_failures(self):
        """测试清除失败记录"""
        from main import record_login_failure, clear_login_failures, check_login_lockout, _login_failures, _rate_limit_lock
        
        # 清理测试数据
        with _rate_limit_lock:
            _login_failures.clear()
        
        ip = "192.168.1.4"
        
        # 记录失败
        record_login_failure(ip)
        record_login_failure(ip)
        
        # 清除
        clear_login_failures(ip)
        
        # 检查是否清除
        with _rate_limit_lock:
            assert ip not in _login_failures
    
    def test_different_ips_independent(self):
        """测试不同 IP 独立计数"""
        from main import record_login_failure, _login_failures, _rate_limit_lock
        
        # 清理测试数据
        with _rate_limit_lock:
            _login_failures.clear()
        
        ip1 = "192.168.1.10"
        ip2 = "192.168.1.11"
        
        # IP1 失败 3 次
        for i in range(3):
            record_login_failure(ip1)
        
        # IP2 失败 1 次
        result2 = record_login_failure(ip2)
        
        # IP2 应该还有 4 次机会
        assert result2["remaining_attempts"] == 4
        
        # 清理
        with _rate_limit_lock:
            _login_failures.clear()


class TestLoginSecurityConfig:
    """测试登录安全配置"""
    
    def test_security_config_exists(self):
        """测试安全配置存在"""
        from main import MAX_LOGIN_FAILURES, LOCKOUT_DURATION, FAILURE_WINDOW
        
        assert MAX_LOGIN_FAILURES > 0
        assert LOCKOUT_DURATION > 0
        assert FAILURE_WINDOW > 0
        
        # 合理性检查
        assert MAX_LOGIN_FAILURES >= 3, "最大失败次数应该 >= 3"
        assert LOCKOUT_DURATION >= 300, "锁定时长应该 >= 5分钟"
    
    def test_lockout_duration_reasonable(self):
        """测试锁定时长合理"""
        from main import LOCKOUT_DURATION
        
        # 锁定时长应该在 5-60 分钟之间
        assert 300 <= LOCKOUT_DURATION <= 3600
