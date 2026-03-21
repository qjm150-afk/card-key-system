#!/usr/bin/env python3
"""
从生产环境导出的SQL文件导入数据到开发环境
"""
import os
import sys
import re
import json
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.storage.database.supabase_client import get_supabase_client

def parse_sql_values(sql_file_path: str) -> list:
    """解析SQL INSERT语句，提取VALUES部分的数据"""
    
    with open(sql_file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 提取列名
    columns_match = re.search(r'INSERT INTO\s+"public"\."card_keys_table"\s*\(([^)]+)\)', content)
    if not columns_match:
        print("无法解析列名")
        return []
    
    columns_str = columns_match.group(1)
    columns = [col.strip().strip('"') for col in columns_str.split(',')]
    print(f"列名: {columns}")
    
    # 提取VALUES部分
    values_match = re.search(r'VALUES\s*(.+)$', content, re.DOTALL)
    if not values_match:
        print("无法解析VALUES部分")
        return []
    
    values_str = values_match.group(1).strip()
    
    # 解析每条记录
    records = []
    current_record = []
    current_value = ""
    in_quotes = False
    quote_char = None
    paren_depth = 0
    
    i = 0
    while i < len(values_str):
        char = values_str[i]
        
        # 处理转义
        if i > 0 and values_str[i-1] == '\\':
            current_value += char
            i += 1
            continue
        
        # 处理引号
        if char in ("'", '"') and paren_depth == 1 and not in_quotes:
            in_quotes = True
            quote_char = char
            i += 1
            continue
        
        if char == quote_char and in_quotes:
            # 检查是否是转义的引号
            if i + 1 < len(values_str) and values_str[i + 1] == quote_char:
                current_value += char
                i += 2
                continue
            else:
                in_quotes = False
                quote_char = None
                i += 1
                continue
        
        # 处理括号
        if char == '(' and not in_quotes:
            paren_depth += 1
            if paren_depth == 1:
                i += 1
                continue
        elif char == ')' and not in_quotes:
            paren_depth -= 1
            if paren_depth == 0:
                # 记录结束
                current_record.append(current_value.strip())
                if len(current_record) == len(columns):
                    record = dict(zip(columns, current_record))
                    # 转换数据类型
                    processed = process_record(record)
                    records.append(processed)
                current_record = []
                current_value = ""
                i += 1
                # 跳过可能的逗号和空格
                while i < len(values_str) and values_str[i] in (',', ' '):
                    i += 1
                continue
        
        # 处理字段分隔符
        if char == ',' and paren_depth == 1 and not in_quotes:
            current_record.append(current_value.strip())
            current_value = ""
            i += 1
            continue
        
        # 普通字符
        if paren_depth >= 1:
            current_value += char
        
        i += 1
    
    print(f"解析完成，共 {len(records)} 条记录")
    return records

def process_record(record: dict) -> dict:
    """处理单条记录，转换数据类型"""
    processed = {}
    
    for key, value in record.items():
        # 处理NULL值
        if value.lower() == 'null' or value == '':
            processed[key] = None
            continue
        
        # 处理数字字段
        if key in ('id', 'status', 'used_count', 'max_uses', 'max_devices'):
            try:
                processed[key] = int(value)
            except:
                processed[key] = value
        elif key in ('expire_at', 'bstudio_create_time', 'last_used_at', 'sold_at'):
            # 时间字段保持字符串
            processed[key] = value
        else:
            processed[key] = value
    
    return processed

def clear_existing_data(client):
    """清空现有数据"""
    print("正在清空现有数据...")
    try:
        # 删除所有卡密
        result = client.table('card_keys_table').delete().neq('id', 0).execute()
        print("已清空 card_keys_table")
        
        # 删除所有卡种
        result = client.table('card_types').delete().neq('id', 0).execute()
        print("已清空 card_types")
    except Exception as e:
        print(f"清空数据时出错: {e}")

def import_data(records: list, batch_size: int = 100):
    """批量导入数据"""
    client = get_supabase_client()
    
    # 先清空现有数据
    clear_existing_data(client)
    
    # 批量插入
    total = len(records)
    imported = 0
    
    for i in range(0, total, batch_size):
        batch = records[i:i + batch_size]
        try:
            result = client.table('card_keys_table').insert(batch).execute()
            imported += len(result.data)
            print(f"已导入 {imported}/{total} 条记录...")
        except Exception as e:
            print(f"导入批次 {i//batch_size + 1} 失败: {e}")
            # 尝试逐条插入
            for record in batch:
                try:
                    client.table('card_keys_table').insert(record).execute()
                    imported += 1
                except Exception as e2:
                    print(f"跳过记录 {record.get('id')}: {e2}")
    
    print(f"\n导入完成: {imported}/{total} 条记录")
    return imported

def run_card_type_migration():
    """运行卡种迁移脚本"""
    print("\n正在运行卡种迁移...")
    os.system(f"python {os.path.join(os.path.dirname(__file__), 'migrate_card_types.py')}")

def main():
    sql_file = '/tmp/card_keys_table_rows.sql'
    
    if not os.path.exists(sql_file):
        print(f"SQL文件不存在: {sql_file}")
        return
    
    print("=" * 50)
    print("开始导入生产环境数据")
    print("=" * 50)
    
    # 1. 解析SQL文件
    print("\n步骤1: 解析SQL文件...")
    records = parse_sql_values(sql_file)
    
    if not records:
        print("没有找到有效的记录")
        return
    
    # 显示样本数据
    print(f"\n样本数据 (第1条):")
    for k, v in list(records[0].items())[:10]:
        print(f"  {k}: {v}")
    
    # 2. 导入数据
    print("\n步骤2: 导入数据到数据库...")
    imported = import_data(records)
    
    # 3. 运行卡种迁移
    print("\n步骤3: 运行卡种迁移...")
    run_card_type_migration()
    
    print("\n" + "=" * 50)
    print("数据导入完成!")
    print("=" * 50)

if __name__ == '__main__':
    main()
