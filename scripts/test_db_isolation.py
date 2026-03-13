#!/usr/bin/env python3
"""测试数据库隔离功能"""
import os
import sys
from datetime import datetime, timedelta

# 添加项目路径
sys.path.insert(0, '/workspace/projects/src')

from storage.database.db_client import get_db_client, reset_db_client

def test_sqlite_mode():
    """测试本地 SQLite 模式"""
    print("=" * 50)
    print("测试本地 SQLite 模式")
    print("=" * 50)
    
    # 临时移除环境变量
    original_url = os.environ.get('COZE_SUPABASE_URL')
    if 'COZE_SUPABASE_URL' in os.environ:
        del os.environ['COZE_SUPABASE_URL']
    
    try:
        client, is_sqlite = get_db_client()
        
        print(f"数据库类型: {'SQLite' if is_sqlite else 'Supabase'}")
        if not is_sqlite:
            print("❌ 本地模式应该使用 SQLite")
            return False
        
        # 测试基本操作
        test_key = f'TEST-SQLITE-{datetime.now().strftime("%Y%m%d%H%M%S")}'
        
        # 插入
        response = client.table('card_keys_table').insert({
            'key_value': test_key,
            'status': 1,
            'feishu_url': 'https://test.feishu.cn'
        }).execute()
        print(f"✓ 插入成功: {test_key}")
        
        # 查询
        response = client.table('card_keys_table').select('*').eq('key_value', test_key).execute()
        assert len(response.data) > 0
        print(f"✓ 查询成功")
        
        # 清理
        client.table('card_keys_table').delete().eq('key_value', test_key).execute()
        print(f"✓ 清理完成")
        
        print("✅ SQLite 模式测试通过！\n")
        return True
        
    except Exception as e:
        print(f"❌ SQLite 模式测试失败: {e}\n")
        return False
    finally:
        # 恢复环境变量
        if original_url:
            os.environ['COZE_SUPABASE_URL'] = original_url
        # 重置客户端缓存
        reset_db_client()

def test_supabase_mode():
    """测试云端 Supabase 模式"""
    print("=" * 50)
    print("测试云端 Supabase 模式")
    print("=" * 50)
    
    if 'COZE_SUPABASE_URL' not in os.environ:
        print("⚠️  未设置 COZE_SUPABASE_URL，跳过云端测试")
        return True
    
    try:
        client, is_sqlite = get_db_client()
        
        print(f"数据库类型: {'SQLite' if is_sqlite else 'Supabase'}")
        if is_sqlite:
            print("❌ 云端模式应该使用 Supabase")
            return False
        
        # 测试查询操作（不修改数据）
        response = client.table('card_keys_table').select('count').execute()
        print(f"✓ 连接成功，可查询数据")
        
        print("✅ Supabase 模式测试通过！\n")
        return True
        
    except Exception as e:
        print(f"❌ Supabase 模式测试失败: {e}\n")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = True
    
    # 测试 SQLite 模式
    if not test_sqlite_mode():
        success = False
    
    # 测试 Supabase 模式
    if not test_supabase_mode():
        success = False
    
    print("=" * 50)
    if success:
        print("🎉 所有测试通过！")
    else:
        print("❌ 部分测试失败")
    print("=" * 50)
    
    sys.exit(0 if success else 1)
