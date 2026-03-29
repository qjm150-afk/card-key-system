#!/usr/bin/env python3
"""
从扣子数据库导出数据并导入到 Supabase（修复版）
"""

import os
import sys
import json
from datetime import datetime
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / 'src'))

# 扣子数据库连接信息
COZE_DATABASE_URL = "postgresql://postgres:25Dee9kvcaV24hEla7@cp-witty-gale-9f6310c2.pg5.aidap-global.cn-beijing.volces.com:5432/postgres?sslmode=require&channel_binding=require"

# Supabase 配置
os.environ['COZE_SUPABASE_URL'] = 'https://ktivyspgzpxrawjtmkck.supabase.co'
os.environ['COZE_SUPABASE_ANON_KEY'] = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imt0aXZ5c3BnenB4cmF3anRta2NrIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQ3NzkwNzIsImV4cCI6MjA5MDM1NTA3Mn0.soWTMdRYmCvJTP7QbyFTniLLaY3P0XQu6bz37ItdZbA'

import psycopg2
from psycopg2.extras import RealDictCursor

print("=" * 70)
print("数据迁移: 扣子数据库 → Supabase（修复版）")
print("=" * 70)
print()

# 只处理核心表
TABLES = ['card_types', 'card_keys_table', 'admin_settings']


def export_from_coze():
    """从扣子数据库导出数据"""
    print("📤 连接扣子数据库...")
    
    try:
        conn = psycopg2.connect(COZE_DATABASE_URL, connect_timeout=30)
        print("   ✅ 连接成功")
        
        exported = {}
        
        for table in TABLES:
            print(f"\n   导出 {table}...")
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(f"SELECT * FROM {table}")
                    rows = cur.fetchall()
                    exported[table] = [dict(row) for row in rows]
                    print(f"      ✅ {len(rows)} 条记录")
            except Exception as e:
                print(f"      ❌ 导出失败: {e}")
                exported[table] = []
        
        conn.close()
        return exported
        
    except Exception as e:
        print(f"   ❌ 连接失败: {e}")
        return None


def import_to_supabase(exported_data):
    """导入数据到 Supabase"""
    print("\n" + "=" * 70)
    print("📥 导入数据到 Supabase...")
    print("=" * 70)
    
    from src.storage.database.supabase_client import get_supabase_client
    
    try:
        client = get_supabase_client()
        print("   ✅ Supabase 连接成功")
    except Exception as e:
        print(f"   ❌ 连接失败: {e}")
        return False
    
    results = {}
    
    # 1. 导入 card_types
    if exported_data.get('card_types'):
        data = exported_data['card_types']
        print(f"\n   导入 card_types ({len(data)} 条)...")
        
        imported, skipped, errors = 0, 0, 0
        for record in data:
            try:
                # 只保留 Supabase 表中存在的字段
                import_record = {
                    'id': record['id'],
                    'name': record['name'],
                    'preview_image': record.get('preview_image'),
                    'preview_enabled': record.get('preview_enabled', False),
                    'status': record.get('status', 1),
                    'preview_image_id': record.get('preview_image_id'),
                    'sort_order': record.get('sort_order', 0),
                    'created_at': record.get('created_at'),
                    'updated_at': record.get('updated_at'),
                    'deleted_at': record.get('deleted_at'),
                }
                
                # 转换 datetime
                for k, v in list(import_record.items()):
                    if hasattr(v, 'isoformat'):
                        import_record[k] = v.isoformat()
                
                client.table('card_types').insert(import_record).execute()
                imported += 1
                
            except Exception as e:
                error_msg = str(e)
                if 'duplicate' in error_msg.lower():
                    skipped += 1
                else:
                    errors += 1
                    if errors <= 3:
                        print(f"      ❌ 错误: {error_msg[:100]}")
        
        print(f"      ✅ 导入: {imported}, 跳过: {skipped}, 错误: {errors}")
        results['card_types'] = {'imported': imported, 'skipped': skipped, 'errors': errors}
    
    # 2. 导入 card_keys_table
    if exported_data.get('card_keys_table'):
        data = exported_data['card_keys_table']
        print(f"\n   导入 card_keys_table ({len(data)} 条)...")
        
        imported, skipped, errors = 0, 0, 0
        for i, record in enumerate(data):
            try:
                # 只保留 Supabase 表中存在的字段
                import_record = {
                    'id': record['id'],
                    'key_value': record['key_value'],
                    'card_type_id': record.get('card_type_id'),
                    'status': record.get('status', 1),
                    'sale_status': record.get('sale_status', 'unsold'),
                    'sales_channel': record.get('sales_channel'),
                    'order_id': record.get('order_id'),
                    'user_note': record.get('user_note'),
                    'feishu_url': record.get('feishu_url'),
                    'feishu_password': record.get('feishu_password'),
                    'link_name': record.get('link_name'),
                    'devices': record.get('devices', '[]'),
                    'max_devices': record.get('max_devices', 5),
                    'expire_at': record.get('expire_at'),
                    'expire_after_days': record.get('expire_after_days'),
                    'activated_at': record.get('activated_at'),
                    'last_used_at': record.get('last_used_at'),
                    'sold_at': record.get('sold_at'),
                    'created_at': record.get('created_at'),
                    'updated_at': record.get('updated_at'),
                }
                
                # 转换 datetime
                for k, v in list(import_record.items()):
                    if hasattr(v, 'isoformat'):
                        import_record[k] = v.isoformat()
                
                client.table('card_keys_table').insert(import_record).execute()
                imported += 1
                
                if (i + 1) % 50 == 0:
                    print(f"      进度: {i + 1}/{len(data)}")
                
            except Exception as e:
                error_msg = str(e)
                if 'duplicate' in error_msg.lower():
                    skipped += 1
                else:
                    errors += 1
                    if errors <= 5:
                        print(f"      ❌ ID {record.get('id')}: {error_msg[:80]}")
        
        print(f"      ✅ 导入: {imported}, 跳过: {skipped}, 错误: {errors}")
        results['card_keys_table'] = {'imported': imported, 'skipped': skipped, 'errors': errors}
    
    # 3. 导入 admin_settings
    if exported_data.get('admin_settings'):
        data = exported_data['admin_settings']
        print(f"\n   导入 admin_settings ({len(data)} 条)...")
        
        imported, skipped, errors = 0, 0, 0
        for record in data:
            try:
                import_record = {
                    'key': record['key'],
                    'value': record.get('value'),
                    'description': record.get('description'),
                    'created_at': record.get('created_at'),
                    'updated_at': record.get('updated_at'),
                }
                
                # 转换 datetime
                for k, v in list(import_record.items()):
                    if hasattr(v, 'isoformat'):
                        import_record[k] = v.isoformat()
                
                client.table('admin_settings').insert(import_record).execute()
                imported += 1
                
            except Exception as e:
                error_msg = str(e)
                if 'duplicate' in error_msg.lower():
                    skipped += 1
                else:
                    errors += 1
                    print(f"      ❌ 错误: {error_msg[:100]}")
        
        print(f"      ✅ 导入: {imported}, 跳过: {skipped}, 错误: {errors}")
        results['admin_settings'] = {'imported': imported, 'skipped': skipped, 'errors': errors}
    
    # 总结
    print("\n" + "=" * 70)
    print("📊 迁移完成")
    print("=" * 70)
    
    total_imported = sum(r.get('imported', 0) for r in results.values())
    total_errors = sum(r.get('errors', 0) for r in results.values())
    
    for table, r in results.items():
        print(f"   {table}: 导入 {r['imported']}, 跳过 {r['skipped']}, 错误 {r['errors']}")
    
    print(f"\n   ✅ 总计导入: {total_imported} 条记录")
    
    return total_imported > 0


def main():
    # 1. 从扣子导出
    exported_data = export_from_coze()
    if not exported_data:
        print("\n❌ 导出失败，终止迁移")
        return False
    
    # 2. 导入到 Supabase
    success = import_to_supabase(exported_data)
    
    return success


if __name__ == '__main__':
    main()
