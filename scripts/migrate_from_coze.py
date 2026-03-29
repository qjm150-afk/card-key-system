#!/usr/bin/env python3
"""
从扣子数据库导出数据并导入到 Supabase
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
print("数据迁移: 扣子数据库 → Supabase")
print("=" * 70)
print()

# 表列表（按依赖顺序）
TABLES = [
    'card_types',
    'card_keys_table', 
    'admin_settings',
    'session_tokens',
    'access_logs',
    'batch_operation_logs',
    'preview_images',
    'link_health_table',
    'feishu_access_records',
    'leak_detection_results',
]


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
                error_msg = str(e)
                if 'does not exist' in error_msg.lower():
                    print(f"      ⏭️ 表不存在，跳过")
                    exported[table] = []
                else:
                    print(f"      ❌ 导出失败: {error_msg}")
                    exported[table] = []
        
        conn.close()
        
        # 保存到文件
        export_file = project_root / 'coze_data_export.json'
        with open(export_file, 'w', encoding='utf-8') as f:
            json.dump({
                'export_time': datetime.now().isoformat(),
                'tables': exported
            }, f, ensure_ascii=False, indent=2, default=str)
        
        print(f"\n💾 数据已保存到: {export_file}")
        
        # 统计
        total = sum(len(v) for v in exported.values())
        print(f"\n📊 导出统计:")
        for table, data in exported.items():
            if data:
                print(f"   {table}: {len(data)} 条")
        print(f"   总计: {total} 条记录")
        
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
    
    # 导入顺序（考虑外键依赖）
    import_order = [
        ('card_types', 'id'),
        ('card_keys_table', 'id'),
        ('admin_settings', 'id'),
        ('session_tokens', 'id'),
        ('access_logs', 'id'),
    ]
    
    results = {}
    
    for table, _ in import_order:
        if table not in exported_data:
            continue
        
        data = exported_data[table]
        if not data:
            print(f"\n   {table}: 无数据，跳过")
            results[table] = {'imported': 0, 'skipped': 0, 'errors': 0}
            continue
        
        print(f"\n   导入 {table} ({len(data)} 条)...")
        
        imported = 0
        skipped = 0
        errors = 0
        
        # 分批导入
        batch_size = 50
        for i in range(0, len(data), batch_size):
            batch = data[i:i + batch_size]
            
            for record in batch:
                try:
                    # 转换 datetime 对象
                    import_record = {}
                    for k, v in record.items():
                        if hasattr(v, 'isoformat'):
                            import_record[k] = v.isoformat()
                        else:
                            import_record[k] = v
                    
                    client.table(table).insert(import_record).execute()
                    imported += 1
                    
                except Exception as e:
                    error_msg = str(e)
                    if 'duplicate' in error_msg.lower() or 'already exists' in error_msg.lower():
                        skipped += 1
                    else:
                        errors += 1
                        if errors <= 3:
                            print(f"      ❌ 错误: {error_msg[:80]}")
            
            progress = min(i + batch_size, len(data))
            if progress % 100 == 0 or progress == len(data):
                print(f"      进度: {progress}/{len(data)}")
        
        results[table] = {'imported': imported, 'skipped': skipped, 'errors': errors}
        status = "✅" if imported > 0 else "⚠️"
        print(f"      {status} 导入: {imported}, 跳过: {skipped}, 错误: {errors}")
    
    # 总结
    print("\n" + "=" * 70)
    print("📊 迁移完成统计")
    print("=" * 70)
    
    total_imported = sum(r['imported'] for r in results.values())
    total_skipped = sum(r['skipped'] for r in results.values())
    total_errors = sum(r['errors'] for r in results.values())
    
    for table, r in results.items():
        print(f"   {table}: 导入 {r['imported']}, 跳过 {r['skipped']}, 错误 {r['errors']}")
    
    print(f"\n   总计: 导入 {total_imported}, 跳过 {total_skipped}, 错误 {total_errors}")
    
    return True


def main():
    # 1. 从扣子导出
    exported_data = export_from_coze()
    if not exported_data:
        print("\n❌ 导出失败，终止迁移")
        return False
    
    # 2. 导入到 Supabase
    success = import_to_supabase(exported_data)
    
    if success:
        print("\n✅ 数据迁移完成！")
        print("\n📋 下一步:")
        print("   1. 访问管理后台验证数据")
        print("   2. 测试卡密验证功能")
    
    return success


if __name__ == '__main__':
    main()
