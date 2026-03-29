#!/usr/bin/env python3
"""
数据迁移脚本 - 从扣子数据库迁移到 Supabase

使用方法：
    1. 设置源数据库环境变量（扣子数据库）
    2. 设置目标数据库环境变量（Supabase）
    3. 运行此脚本

环境变量：
    源数据库（扣子）：
        SOURCE_PGHOST=xxx
        SOURCE_PGPORT=5432
        SOURCE_PGDATABASE=postgres
        SOURCE_PGUSER=postgres
        SOURCE_PGPASSWORD=xxx
    
    目标数据库（Supabase）：
        SUPABASE_URL=https://xxx.supabase.co
        SUPABASE_KEY=eyJxxx
"""

import os
import sys
import json
from datetime import datetime
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import psycopg2
from psycopg2.extras import RealDictCursor


def get_source_connection():
    """获取源数据库连接（扣子数据库）"""
    host = os.getenv("SOURCE_PGHOST")
    port = os.getenv("SOURCE_PGPORT", "5432")
    database = os.getenv("SOURCE_PGDATABASE", "postgres")
    user = os.getenv("SOURCE_PGUSER", "postgres")
    password = os.getenv("SOURCE_PGPASSWORD")
    
    if not all([host, user, password]):
        raise ValueError("请设置源数据库环境变量: SOURCE_PGHOST, SOURCE_PGUSER, SOURCE_PGPASSWORD")
    
    return psycopg2.connect(
        host=host,
        port=port,
        database=database,
        user=user,
        password=password,
        connect_timeout=30
    )


def get_target_client():
    """获取目标数据库客户端（Supabase）"""
    from src.storage.database.supabase_client import get_supabase_client
    return get_supabase_client()


def export_table_data(conn, table_name: str) -> list:
    """从源数据库导出表数据"""
    print(f"  导出 {table_name}...")
    
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(f"SELECT * FROM {table_name}")
        rows = cur.fetchall()
        return [dict(row) for row in rows]


def import_table_data(client, table_name: str, data: list) -> dict:
    """导入数据到 Supabase"""
    result = {
        'table': table_name,
        'total': len(data),
        'imported': 0,
        'skipped': 0,
        'errors': []
    }
    
    if not data:
        print(f"  {table_name}: 无数据")
        return result
    
    # 分批导入（每批100条）
    batch_size = 100
    for i in range(0, len(data), batch_size):
        batch = data[i:i + batch_size]
        
        for record in batch:
            try:
                # 移除 id，让 Supabase 自动生成
                import_record = {k: v for k, v in record.items() if k != 'id'}
                
                # 处理 datetime 对象
                for key, value in import_record.items():
                    if hasattr(value, 'isoformat'):
                        import_record[key] = value.isoformat()
                
                client.table(table_name).insert(import_record).execute()
                result['imported'] += 1
                
            except Exception as e:
                error_msg = str(e)
                if 'duplicate' in error_msg.lower() or 'already exists' in error_msg.lower():
                    result['skipped'] += 1
                else:
                    result['errors'].append({
                        'id': record.get('id'),
                        'error': error_msg[:100]
                    })
        
        print(f"    进度: {min(i + batch_size, len(data))}/{len(data)}")
    
    return result


def main():
    print("=" * 70)
    print("数据迁移工具: 扣子数据库 → Supabase")
    print("=" * 70)
    print()
    
    # 1. 连接源数据库
    print("📡 连接源数据库（扣子）...")
    try:
        source_conn = get_source_connection()
        print("   ✅ 连接成功")
    except Exception as e:
        print(f"   ❌ 连接失败: {e}")
        print()
        print("请设置以下环境变量:")
        print("  export SOURCE_PGHOST=xxx")
        print("  export SOURCE_PGPORT=5432")
        print("  export SOURCE_PGDATABASE=postgres")
        print("  export SOURCE_PGUSER=postgres")
        print("  export SOURCE_PGPASSWORD=xxx")
        return False
    
    # 2. 连接目标数据库
    print("📡 连接目标数据库（Supabase）...")
    try:
        target_client = get_target_client()
        print("   ✅ 连接成功")
    except Exception as e:
        print(f"   ❌ 连接失败: {e}")
        print()
        print("请设置以下环境变量:")
        print("  export SUPABASE_URL=https://xxx.supabase.co")
        print("  export SUPABASE_KEY=eyJxxx")
        return False
    
    print()
    
    # 3. 导出数据
    print("📤 导出数据...")
    tables = [
        'card_types',
        'card_keys_table',
        'access_logs',
        'session_tokens',
        'admin_settings',
        'batch_operation_logs',
        'preview_images',
    ]
    
    exported_data = {}
    for table_name in tables:
        try:
            data = export_table_data(source_conn, table_name)
            exported_data[table_name] = data
            print(f"   ✅ {table_name}: {len(data)} 条记录")
        except Exception as e:
            print(f"   ⚠️ {table_name}: 表不存在或导出失败 - {e}")
    
    # 保存导出数据到文件
    export_file = project_root / 'migration_export.json'
    with open(export_file, 'w', encoding='utf-8') as f:
        json.dump({
            'export_time': datetime.now().isoformat(),
            'tables': exported_data
        }, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n💾 数据已保存到: {export_file}")
    
    print()
    
    # 4. 导入数据
    print("📥 导入数据到 Supabase...")
    
    # 导入顺序（考虑外键依赖）
    import_order = [
        'card_types',
        'card_keys_table',
        'session_tokens',
        'admin_settings',
        'access_logs',
        'batch_operation_logs',
        'preview_images',
    ]
    
    for table_name in import_order:
        if table_name not in exported_data:
            continue
        
        data = exported_data[table_name]
        if not data:
            print(f"   ⏭️ {table_name}: 无数据，跳过")
            continue
        
        result = import_table_data(target_client, table_name, data)
        
        status = "✅" if result['imported'] > 0 else "⚠️"
        print(f"   {status} {table_name}: 导入 {result['imported']}, 跳过 {result['skipped']}")
        
        if result['errors']:
            print(f"      ❌ 错误 {len(result['errors'])} 条")
    
    # 5. 同步序列（解决ID自增问题）
    print("\n🔄 同步数据库序列...")
    try:
        from src.storage.database.postgres_client import PostgresClient
        
        # 使用 Supabase 的数据库直连
        db_url = os.getenv("DATABASE_URL")
        if db_url:
            pg_client = PostgresClient(db_url)
            pg_client.sync_sequence('card_keys_table')
            pg_client.sync_sequence('card_types')
            print("   ✅ 序列同步完成")
    except Exception as e:
        print(f"   ⚠️ 序列同步失败（可忽略）: {e}")
    
    print()
    print("=" * 70)
    print("迁移完成！")
    print("=" * 70)
    
    # 关闭连接
    source_conn.close()
    
    return True


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
