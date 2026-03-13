#!/usr/bin/env python3
"""
数据恢复脚本
从备份文件恢复数据到数据库

使用方法：
    python scripts/restore_data.py --list              # 列出所有备份
    python scripts/restore_data.py --latest            # 恢复最新备份
    python scripts/restore_data.py --file backup.json  # 恢复指定备份
    
⚠️ 警告：恢复操作会清空目标表并重新导入数据，请谨慎使用！
"""

import os
import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.storage.database.supabase_client import get_supabase_client


# 备份目录
BACKUP_DIR = project_root / 'backups'


def list_backups():
    """列出所有备份文件"""
    if not BACKUP_DIR.exists():
        print("暂无备份文件")
        return []
    
    backup_files = sorted(
        BACKUP_DIR.glob('backup_*.json'),
        key=lambda f: f.stat().st_mtime,
        reverse=True
    )
    
    if not backup_files:
        print("暂无备份文件")
        return []
    
    print("\n" + "=" * 60)
    print("备份文件列表")
    print("=" * 60)
    
    for i, backup_file in enumerate(backup_files, 1):
        stat = backup_file.stat()
        created_at = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
        size_kb = stat.st_size / 1024
        
        # 读取备份信息
        try:
            with open(backup_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            total_records = sum(t['count'] for t in data['tables'].values())
        except:
            total_records = '?'
        
        print(f"\n{i}. {backup_file.name}")
        print(f"   创建时间: {created_at}")
        print(f"   文件大小: {size_kb:.2f} KB")
        print(f"   记录总数: {total_records}")
    
    return backup_files


def get_latest_backup() -> Path:
    """获取最新的备份文件"""
    if not BACKUP_DIR.exists():
        return None
    
    backup_files = sorted(
        BACKUP_DIR.glob('backup_*.json'),
        key=lambda f: f.stat().st_mtime,
        reverse=True
    )
    
    return backup_files[0] if backup_files else None


def restore_table(client, table_name: str, records: list, truncate: bool = True) -> dict:
    """恢复单个表的数据"""
    print(f"\n恢复表: {table_name}")
    
    try:
        # 清空表（如果需要）
        if truncate:
            print(f"  清空表...")
            client.table(table_name).delete().neq('id', 0).execute()
        
        # 批量插入数据
        if records:
            batch_size = 100
            inserted = 0
            
            for i in range(0, len(records), batch_size):
                batch = records[i:i + batch_size]
                
                # 移除 id 字段（让数据库自动生成）
                for record in batch:
                    record.pop('id', None)
                
                client.table(table_name).insert(batch).execute()
                inserted += len(batch)
                print(f"  已插入 {inserted}/{len(records)} 条记录...")
            
            print(f"  ✅ 共恢复 {len(records)} 条记录")
        else:
            print(f"  ℹ️ 无数据需要恢复")
        
        return {'success': True, 'count': len(records)}
    
    except Exception as e:
        print(f"  ❌ 恢复失败: {e}")
        return {'success': False, 'error': str(e)}


def restore_backup(backup_path: Path, tables: list = None, skip_confirm: bool = False):
    """从备份文件恢复数据"""
    
    print("=" * 60)
    print("数据恢复工具")
    print("=" * 60)
    print(f"\n备份文件: {backup_path}")
    
    # 读取备份文件
    with open(backup_path, 'r', encoding='utf-8') as f:
        backup_data = json.load(f)
    
    # 显示备份信息
    print(f"备份时间: {backup_data['created_at']}")
    print(f"\n备份内容:")
    for table_name, table_data in backup_data['tables'].items():
        status = "✅" if 'error' not in table_data else "❌"
        print(f"  {status} {table_name}: {table_data['count']} 条记录")
    
    # 确认恢复
    if not skip_confirm:
        print("\n" + "⚠️ " * 20)
        print("警告：恢复操作会清空目标表并重新导入数据！")
        print("⚠️ " * 20)
        
        confirm = input("\n确认要恢复数据吗？(yes/no): ")
        if confirm.lower() != 'yes':
            print("已取消恢复")
            return False
    
    # 获取数据库客户端
    print("\n连接数据库...")
    client = get_supabase_client()
    
    # 恢复数据
    print("\n开始恢复数据...")
    
    # 如果指定了要恢复的表
    if tables:
        table_names = tables
    else:
        table_names = list(backup_data['tables'].keys())
    
    results = {}
    for table_name in table_names:
        if table_name in backup_data['tables']:
            table_data = backup_data['tables'][table_name]
            if 'error' not in table_data:
                results[table_name] = restore_table(client, table_name, table_data['data'])
            else:
                print(f"\n跳过表 {table_name}（备份时有错误）")
                results[table_name] = {'success': False, 'error': '备份时有错误'}
        else:
            print(f"\n跳过表 {table_name}（备份中不存在）")
            results[table_name] = {'success': False, 'error': '备份中不存在'}
    
    # 输出结果
    print("\n" + "=" * 60)
    print("恢复完成！")
    print("=" * 60)
    print("\n恢复结果:")
    for table_name, result in results.items():
        status = "✅" if result.get('success') else "❌"
        print(f"  {status} {table_name}: {result.get('count', 0)} 条记录")
    
    return True


def main():
    parser = argparse.ArgumentParser(description='数据恢复工具')
    parser.add_argument('--list', '-l', action='store_true', help='列出所有备份文件')
    parser.add_argument('--latest', action='store_true', help='恢复最新备份')
    parser.add_argument('--file', '-f', help='指定备份文件名')
    parser.add_argument('--tables', '-t', help='指定要恢复的表（逗号分隔）')
    parser.add_argument('--yes', '-y', action='store_true', help='跳过确认')
    
    args = parser.parse_args()
    
    # 列出备份
    if args.list:
        list_backups()
        return
    
    # 确定备份文件
    if args.file:
        backup_path = BACKUP_DIR / args.file
        if not backup_path.exists():
            print(f"❌ 备份文件不存在: {backup_path}")
            sys.exit(1)
    elif args.latest:
        backup_path = get_latest_backup()
        if not backup_path:
            print("❌ 没有找到备份文件")
            sys.exit(1)
        print(f"使用最新备份: {backup_path.name}")
    else:
        # 默认显示帮助
        parser.print_help()
        return
    
    # 解析要恢复的表
    tables = args.tables.split(',') if args.tables else None
    
    # 执行恢复
    try:
        restore_backup(backup_path, tables, args.yes)
    except Exception as e:
        print(f"\n❌ 恢复失败: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
