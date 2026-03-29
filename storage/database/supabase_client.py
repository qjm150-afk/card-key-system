"""
Supabase 数据库客户端

用于阿里云FC部署后的数据库连接
"""
import os
from typing import Optional
from supabase import create_client, Client


class SupabaseClient:
    """Supabase数据库客户端封装"""
    
    _instance: Optional[Client] = None
    
    @classmethod
    def get_client(cls) -> Client:
        """获取Supabase客户端（单例模式）"""
        if cls._instance is None:
            url = os.getenv("SUPABASE_URL")
            key = os.getenv("SUPABASE_KEY")
            
            if not url or not key:
                raise ValueError(
                    "SUPABASE_URL and SUPABASE_KEY environment variables must be set"
                )
            
            cls._instance = create_client(url, key)
        
        return cls._instance


def get_supabase_client() -> Client:
    """获取Supabase客户端"""
    return SupabaseClient.get_client()


def get_db_client():
    """
    获取数据库客户端（兼容旧接口）
    
    根据环境变量自动选择：
    - 有SUPABASE_URL：使用Supabase
    - 有DATABASE_URL：使用PostgreSQL
    """
    supabase_url = os.getenv("SUPABASE_URL")
    database_url = os.getenv("DATABASE_URL")
    
    if supabase_url:
        return get_supabase_client()
    elif database_url:
        # 兼容扣子内置数据库
        from storage.database.postgres_client import get_postgres_client
        return get_postgres_client()
    else:
        raise ValueError("Either SUPABASE_URL or DATABASE_URL must be set")
