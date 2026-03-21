"""
卡种管理体系数据迁移脚本

功能：
1. 按 link_name 自动创建卡种
2. 关联现有卡密到对应卡种

执行方式：
python scripts/migrate_card_types.py
"""

import os
import sys

# 添加项目根目录到 Python 路径
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, 'src'))

from datetime import datetime


def get_db_client():
    """获取数据库客户端"""
    from storage.database.db_client import get_db_client
    client, _ = get_db_client()
    return client


def migrate():
    """执行数据迁移"""
    print("=" * 60)
    print("卡种管理体系数据迁移脚本")
    print("=" * 60)
    
    client = get_db_client()
    print(f"[INFO] 数据库客户端类型: {type(client).__name__}")
    
    # 1. 查询所有不同的 link_name 及其关联的飞书链接
    print("\n[STEP 1] 查询现有卡密的 link_name 分组...")
    
    # 获取所有卡密的 link_name, feishu_url, feishu_password
    response = client.table('card_keys_table').select('id, link_name, feishu_url, feishu_password').execute()
    all_cards = response.data
    
    print(f"[INFO] 总卡密数: {len(all_cards)}")
    
    # 按 link_name 分组
    link_name_groups = {}
    for card in all_cards:
        link_name = card.get('link_name') or ''
        feishu_url = card.get('feishu_url') or ''
        feishu_password = card.get('feishu_password') or ''
        
        # 使用 link_name 作为分组键，如果为空则使用 feishu_url
        group_key = link_name.strip() if link_name.strip() else (feishu_url.strip() if feishu_url.strip() else '__default__')
        
        if group_key not in link_name_groups:
            link_name_groups[group_key] = {
                'name': link_name.strip() if link_name.strip() else f'默认卡种-{group_key[:20]}',
                'feishu_url': feishu_url,
                'feishu_password': feishu_password,
                'card_ids': []
            }
        link_name_groups[group_key]['card_ids'].append(card['id'])
    
    print(f"[INFO] 发现 {len(link_name_groups)} 个分组")
    
    # 2. 为每个分组创建卡种
    print("\n[STEP 2] 创建卡种...")
    
    card_type_map = {}  # group_key -> card_type_id
    
    for group_key, group_data in link_name_groups.items():
        # 检查是否已存在同名卡种
        existing = client.table('card_types').select('id').eq('name', group_data['name']).execute()
        
        if existing.data:
            # 已存在，使用现有卡种
            card_type_id = existing.data[0]['id']
            print(f"[INFO] 卡种 '{group_data['name']}' 已存在，ID: {card_type_id}")
        else:
            # 创建新卡种
            new_type = {
                'name': group_data['name'],
                'preview_enabled': False,
                'status': 1,
                'created_at': datetime.now().isoformat()
            }
            result = client.table('card_types').insert(new_type).execute()
            card_type_id = result.data[0]['id']
            print(f"[INFO] 创建卡种 '{group_data['name']}', ID: {card_type_id}")
        
        card_type_map[group_key] = {
            'id': card_type_id,
            'card_ids': group_data['card_ids'],
            'feishu_url': group_data['feishu_url'],
            'feishu_password': group_data['feishu_password']
        }
    
    # 3. 更新卡密关联卡种
    print("\n[STEP 3] 关联卡密到卡种...")
    
    updated_count = 0
    for group_key, type_data in card_type_map.items():
        card_type_id = type_data['id']
        card_ids = type_data['card_ids']
        
        if not card_ids:
            continue
        
        # 批量更新卡密的 card_type_id
        update_result = client.table('card_keys_table').update({
            'card_type_id': card_type_id
        }).in_('id', card_ids).execute()
        
        updated_count += len(card_ids)
        print(f"[INFO] 更新 {len(card_ids)} 条卡密关联到卡种 ID: {card_type_id}")
    
    print("\n" + "=" * 60)
    print(f"[DONE] 迁移完成！")
    print(f"  - 创建卡种: {len(card_type_map)} 个")
    print(f"  - 更新卡密: {updated_count} 条")
    print("=" * 60)


if __name__ == "__main__":
    migrate()
