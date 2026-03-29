#!/usr/bin/env python3
"""
测试 Supabase 连接
"""

import os
import sys
from pathlib import Path

# 设置环境变量
os.environ['COZE_SUPABASE_URL'] = 'https://ktivyspgzpxrawjtmkckr.supabase.co'
os.environ['COZE_SUPABASE_ANON_KEY'] = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imt0aXZ5c3BnenB4cmF3anRta2NrIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQ3NzkwNzIsImV4cCI6MjA5MDM1NTA3Mn0.soWTMdRYmCvJTP7QbyFTniLLaY3P0XQu6bz37ItdZbA'

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / 'src'))

print("=" * 60)
print("测试 Supabase 连接")
print("=" * 60)

try:
    from src.storage.database.supabase_client import get_supabase_client
    
    print("\n1. 连接 Supabase...")
    client = get_supabase_client()
    print("   ✅ 连接成功")
    
    print("\n2. 检查表结构...")
    
    # 检查 card_types 表
    response = client.table('card_types').select('*').limit(1).execute()
    print(f"   ✅ card_types 表存在，当前 {len(response.data)} 条记录")
    
    # 检查 card_keys_table 表
    response = client.table('card_keys_table').select('*').limit(1).execute()
    print(f"   ✅ card_keys_table 表存在，当前 {len(response.data)} 条记录")
    
    # 检查 admin_settings 表
    response = client.table('admin_settings').select('*').execute()
    print(f"   ✅ admin_settings 表存在，当前 {len(response.data)} 条记录")
    
    print("\n" + "=" * 60)
    print("✅ Supabase 连接测试通过！")
    print("=" * 60)
    
    print("\n📋 下一步：")
    print("1. 访问管理后台: https://你的域名/admin.html")
    print("2. 使用默认密码登录: QJM150")
    print("3. 添加卡种和卡密")
    
except Exception as e:
    print(f"\n❌ 连接失败: {e}")
    import traceback
    traceback.print_exc()
