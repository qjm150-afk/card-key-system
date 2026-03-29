"""
数据库客户端 - 简化版

迁移到扣子默认方案后，统一使用 PostgreSQL 数据库：
- 开发环境：扣子平台自动注入 DATABASE_URL（开发环境数据库）
- 生产环境：扣子平台自动注入 DATABASE_URL（生产环境数据库）

环境变量说明：
- DATABASE_URL: PostgreSQL 连接字符串（扣子平台自动注入）
- PGDATABASE_URL: PostgreSQL 连接字符串（备选）

注意：
- 已移除 SQLite 支持，不再需要 LOCAL_DEV_MODE 环境变量
- 开发环境和生产环境使用相同的数据库类型（PostgreSQL）
- 环境切换由扣子平台自动处理
"""

import os
from typing import Optional, Tuple

# 全局客户端缓存
_db_client = None


def get_db_mode() -> str:
    """获取当前数据库模式名称"""
    return "postgresql (coze)"


def is_local_dev_mode() -> bool:
    """判断是否为本地开发模式（已废弃，保留兼容性）"""
    return False


def is_production() -> bool:
    """判断是否为生产环境（已废弃，保留兼容性）"""
    return True


def get_db_client() -> Tuple["PostgresClient", bool]:
    """获取数据库客户端
    
    返回：
        (client, is_sqlite) - 客户端对象和是否为 SQLite 的标志
    
    注意：
        - is_sqlite 始终为 False（不再使用 SQLite）
        - 优先使用 Supabase（如果设置了 COZE_SUPABASE_URL）
        - 否则使用扣子平台注入的数据库
    """
    global _db_client
    
    if _db_client is not None:
        return _db_client, False
    
    # 检查是否配置了 Supabase
    supabase_url = os.getenv("COZE_SUPABASE_URL") or os.getenv("SUPABASE_URL")
    
    if supabase_url:
        # 使用 Supabase 客户端
        from .supabase_client import get_supabase_client
        _db_client = get_supabase_client()
        return _db_client, False
    
    # 使用 PostgreSQL 客户端（扣子平台数据库）
    from .postgres_client import get_postgres_client
    
    _db_client = get_postgres_client()
    return _db_client, False
