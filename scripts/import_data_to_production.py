#!/usr/bin/env python3
"""
数据导入脚本 - 将开发环境数据导入到生产环境

使用方法：
    python scripts/import_data_to_production.py

说明：
    此脚本会将 data_export_for_production.json 中的数据导入到当前环境的数据库
    用于将开发环境的数据迁移到生产环境
"""

import os
import sys
import json
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 确保使用 Supabase（生产环境）
if 'LOCAL_DEV_MODE' in os.environ:
    del os.environ['LOCAL_DEV_MODE']

from src.storage.database.supabase_client import get_supabase_client


def import_table(client, table_name: str, data: list, clear_existing: bool = False) -> dict:
    """
    导入单个表的数据
    
    Args:
        client: Supabase 客户端
        table_name: 表名
        data: 数据列表
        clear_existing: 是否清除现有数据
    
    Returns:
        导入结果统计
    """
    result = {
        'table': table_name,
        'imported': 0,
        'skipped': 0,
        'errors': []
    }
    
    if not data:
        print(f"  ⚠️ {table_name}: 无数据需要导入")
        return result
    
    # 可选：清除现有数据
    if clear_existing:
        try:
            # 先获取所有 ID
            existing = client.table(table_name).select('id').execute()
            if existing.data:
                ids = [row['id'] for row in existing.data]
                # 分批删除（每次最多100条）
                for i in range(0, len(ids), 100):
                    batch_ids = ids[i:i+100]
                    client.table(table_name).delete().in_('id', batch_ids).execute()
                print(f"  🗑️ 已清除 {len(ids)} 条现有数据")
        except Exception as e:
            print(f"  ⚠️ 清除数据失败: {e}")
    
    # 导入数据（移除 id 字段，让数据库自动生成）
    for record in data:
        try:
            # 复制记录，移除 id 让数据库自动生成
            import_record = {k: v for k, v in record.items() if k != 'id'}
            
            # 插入数据
            client.table(table_name).insert(import_record).execute()
            result['imported'] += 1
        except Exception as e:
            error_msg = str(e)
            # 忽略重复键错误
            if 'duplicate' in error_msg.lower() or 'already exists' in error_msg.lower():
                result['skipped'] += 1
            else:
                result['errors'].append({
                    'record': record.get('id', 'unknown'),
                    'error': error_msg
                })
    
    return result


def main():
    print("=" * 70)
    print("数据导入工具 - 开发环境 → 生产环境")
    print("=" * 70)
    print()
    
    # 数据文件路径
    data_file = project_root / 'data_export_for_production.json'
    
    if not data_file.exists():
        # 尝试 /tmp 目录
        data_file = Path('/tmp/data_export_for_production.json')
    
    if not data_file.exists():
        print("❌ 错误: 未找到数据导出文件")
        print("   请先在开发环境中运行数据导出，并将文件放到项目根目录")
        return False
    
    # 读取数据
    print(f"📂 读取数据文件: {data_file}")
    with open(data_file, 'r', encoding='utf-8') as f:
        export_data = json.load(f)
    
    print(f"   导出时间: {export_data.get('export_time', '未知')}")
    print()
    
    # 连接数据库
    print("🔌 连接数据库...")
    client = get_supabase_client()
    print("   ✅ 连接成功")
    print()
    
    # 导入数据
    print("📥 开始导入数据...")
    print()
    
    # 导入顺序（注意外键依赖）
    import_order = ['card_keys_table', 'batch_operation_logs', 'access_logs', 'link_health_table']
    
    total_imported = 0
    total_skipped = 0
    
    for table_name in import_order:
        if table_name not in export_data.get('tables', {}):
            continue
        
        table_data = export_data['tables'][table_name]
        if table_data.get('error'):
            print(f"  ⚠️ {table_name}: 源数据有错误，跳过")
            continue
        
        result = import_table(
            client, 
            table_name, 
            table_data.get('data', []),
            clear_existing=False  # 不清除现有数据，避免覆盖生产数据
        )
        
        status = "✅" if result['imported'] > 0 else "⚠️"
        print(f"  {status} {table_name}: 导入 {result['imported']} 条, 跳过 {result['skipped']} 条")
        
        if result['errors']:
            print(f"     ❌ 错误 {len(result['errors'])} 条:")
            for err in result['errors'][:3]:
                print(f"        - ID {err['record']}: {err['error'][:50]}...")
        
        total_imported += result['imported']
        total_skipped += result['skipped']
    
    print()
    print("=" * 70)
    print("导入完成")
    print("=" * 70)
    print(f"总计导入: {total_imported} 条")
    print(f"跳过重复: {total_skipped} 条")
    
    return True


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='数据导入工具')
    parser.add_argument('--clear', action='store_true', help='导入前清除现有数据')
    
    args = parser.parse_args()
    
    success = main()
    sys.exit(0 if success else 1)
