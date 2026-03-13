#!/usr/bin/env python3
"""
数据备份脚本
在部署前执行，导出所有数据到 JSON 文件

使用方法：
    python scripts/backup_data.py
    python scripts/backup_data.py --output custom_backup.json
"""

import os
import sys
import json
from datetime import datetime
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 设置生产环境变量（确保连接 Supabase）
os.environ.setdefault('BACKUP_MODE', 'production')

from src.storage.database.supabase_client import get_supabase_client


# 备份目录
BACKUP_DIR = project_root / 'backups'


def ensure_backup_dir():
    """确保备份目录存在"""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    return BACKUP_DIR


def get_all_records(client, table_name: str, batch_size: int = 1000) -> list:
    """获取表中所有记录（分批获取）"""
    all_records = []
    offset = 0
    
    while True:
        response = client.table(table_name).select('*').range(offset, offset + batch_size - 1).execute()
        
        if not response.data:
            break
        
        all_records.extend(response.data)
        
        if len(response.data) < batch_size:
            break
        
        offset += batch_size
        print(f"  已获取 {len(all_records)} 条记录...")
    
    return all_records


def backup_table(client, table_name: str) -> dict:
    """备份单个表"""
    print(f"\n正在备份表: {table_name}")
    
    try:
        records = get_all_records(client, table_name)
        print(f"  ✅ 共 {len(records)} 条记录")
        return {
            'table_name': table_name,
            'count': len(records),
            'data': records
        }
    except Exception as e:
        print(f"  ❌ 备份失败: {e}")
        return {
            'table_name': table_name,
            'count': 0,
            'data': [],
            'error': str(e)
        }


def backup_all_tables(client) -> dict:
    """备份所有表"""
    tables = [
        'card_keys_table',
        'access_logs',
        'batch_operation_logs'
    ]
    
    results = {}
    
    for table_name in tables:
        results[table_name] = backup_table(client, table_name)
    
    return results


def create_backup(output_file: str = None) -> str:
    """创建备份文件"""
    
    print("=" * 60)
    print("数据备份工具")
    print("=" * 60)
    
    # 确保备份目录存在
    ensure_backup_dir()
    
    # 生成备份文件名
    if not output_file:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = f"backup_{timestamp}.json"
    
    output_path = BACKUP_DIR / output_file
    
    # 获取数据库客户端
    print("\n连接数据库...")
    client = get_supabase_client()
    
    # 备份所有表
    print("\n开始备份数据...")
    backup_data = {
        'version': '1.0',
        'created_at': datetime.now().isoformat(),
        'tables': backup_all_tables(client)
    }
    
    # 统计信息
    total_records = sum(t['count'] for t in backup_data['tables'].values())
    
    # 写入文件
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(backup_data, f, ensure_ascii=False, indent=2)
    
    # 输出结果
    print("\n" + "=" * 60)
    print("备份完成！")
    print("=" * 60)
    print(f"\n备份文件: {output_path}")
    print(f"文件大小: {output_path.stat().st_size / 1024:.2f} KB")
    print(f"\n数据统计:")
    for table_name, table_data in backup_data['tables'].items():
        status = "✅" if 'error' not in table_data else "❌"
        print(f"  {status} {table_name}: {table_data['count']} 条记录")
    print(f"\n总计: {total_records} 条记录")
    
    return str(output_path)


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='数据备份工具')
    parser.add_argument('--output', '-o', help='指定输出文件名')
    
    args = parser.parse_args()
    
    try:
        backup_path = create_backup(args.output)
        print(f"\n✅ 备份成功: {backup_path}")
    except Exception as e:
        print(f"\n❌ 备份失败: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
