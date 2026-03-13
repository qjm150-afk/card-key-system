"""
卡密验证系统 - 主入口
使用 FastAPI + Supabase 连接 Coze 内置数据库
"""

import os
import sys
import logging
import uuid
import secrets
import csv
import io
import json
import re
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Query, Request, File, UploadFile
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# 确保模块导入路径正确（支持从任意目录运行）
_current_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_current_dir)
# 项目根目录和 src 目录都加入路径，支持 from storage.xxx 导入
for _p in [_parent_dir, _current_dir]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 创建 FastAPI 应用
app = FastAPI(title="卡密验证系统")

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件目录
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


# ==================== API 模型 ====================

class ValidateRequest(BaseModel):
    """验证请求"""
    card_key: str
    device_id: Optional[str] = None  # 设备ID


class ValidateResponse(BaseModel):
    """验证响应"""
    can_access: bool
    url: str = ""
    password: str = ""
    msg: str = ""


class CardKeyCreate(BaseModel):
    """创建卡密"""
    key_value: str
    status: int = 1
    user_note: Optional[str] = ""
    feishu_url: Optional[str] = ""
    feishu_password: Optional[str] = ""
    link_name: Optional[str] = ""
    expire_days: Optional[int] = None  # 有效期天数
    max_uses: int = 1  # 最大使用次数


class CardKeyUpdate(BaseModel):
    """更新卡密"""
    key_value: Optional[str] = None
    status: Optional[int] = None
    user_note: Optional[str] = None
    feishu_url: Optional[str] = None
    feishu_password: Optional[str] = None
    link_name: Optional[str] = None
    expire_at: Optional[str] = None
    max_uses: Optional[int] = None
    sale_status: Optional[str] = None  # 销售状态
    order_id: Optional[str] = None  # 订单号
    sales_channel: Optional[str] = None  # 销售渠道


class BatchGenerateRequest(BaseModel):
    """批量生成卡密请求"""
    count: int  # 生成数量
    prefix: str = "CSS"  # 卡密前缀
    feishu_url: str = ""  # 飞书链接
    feishu_password: str = ""  # 飞书密码
    link_name: str = ""  # 链接名称
    expire_at: Optional[str] = None  # 过期时间（ISO格式）
    max_uses: int = 1  # 最大使用次数
    user_note: str = ""  # 备注
    sales_channel: str = ""  # 销售渠道


class BatchOperation(BaseModel):
    """批量操作"""
    ids: List[int]
    action: str  # delete, activate, deactivate
    feishu_url: Optional[str] = None
    feishu_password: Optional[str] = None


class BatchUpdateRequest(BaseModel):
    """批量更新请求"""
    filters: Optional[dict] = None  # 筛选条件（可选）
    ids: Optional[list] = None  # 指定ID列表（可选，与filters二选一）
    updates: dict  # 更新字段
    remark: Optional[str] = None  # 操作备注


class LoginRequest(BaseModel):
    """登录请求"""
    password: str


# ==================== 管理员认证 ====================

# 管理员密码（从环境变量读取，默认为 QJM150）
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "QJM150")

# 存储有效的 token（生产环境应使用 Redis 等）
VALID_TOKENS = {}

# Token 有效期（24小时）
TOKEN_EXPIRE_HOURS = 24


def create_token() -> str:
    """创建 token"""
    token = secrets.token_urlsafe(32)
    VALID_TOKENS[token] = datetime.now() + timedelta(hours=TOKEN_EXPIRE_HOURS)
    return token


def verify_token(token: str) -> bool:
    """验证 token"""
    if not token:
        return False
    if token not in VALID_TOKENS:
        return False
    if datetime.now() > VALID_TOKENS[token]:
        del VALID_TOKENS[token]
        return False
    return True


def get_token_from_request(request: Request) -> str:
    """从请求中获取 token"""
    # 从 Authorization header 获取
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    # 从 cookie 获取
    return request.cookies.get("admin_token", "")


# ==================== 数据库客户端 ====================

def get_supabase_client():
    """
    获取数据库客户端（自动选择模式）
    - 云端部署：使用 Coze Supabase
    - 本地开发：使用 SQLite
    """
    from storage.database.db_client import get_db_client
    client, _ = get_db_client()
    return client


def get_db_mode():
    """获取当前数据库模式"""
    from storage.database.db_client import get_db_mode as _get_db_mode
    return _get_db_mode()


def generate_card_key(prefix: str = "CSS") -> str:
    """
    生成卡密
    格式: CSS-XXXX-XXXX-XXXX (16进制字符)
    """
    # 生成12位16进制字符，分成3组
    chars = "0123456789ABCDEF"
    parts = []
    for _ in range(3):
        part = ''.join(secrets.choice(chars) for _ in range(4))
        parts.append(part)
    return f"{prefix}-{'-'.join(parts)}"


def add_feishu_embed_params(url: str) -> str:
    """
    为飞书多维表格嵌入链接添加官方参数
    
    官方支持的参数（来源：飞书文档）：
    - hideHeader=1: 隐藏头部（可解决"进入原应用"按钮问题）
    - hideSidebar=1: 隐藏侧边栏
    - vc=true: 隐藏新增视图，工具栏上移
    
    注意：飞书官方声明 iframe 嵌入支持不完善，可能有兼容性问题
    """
    if not url:
        return url
    
    # 飞书多维表格链接特征
    feishu_patterns = [
        'feishu.cn/base/',
        'feishu.cn/app/',
        'larksuite.com/base/',
        'larksuite.com/app/',
        'bytedance.larkoffice.com/'
    ]
    
    # 检查是否为飞书链接
    is_feishu = any(pattern in url for pattern in feishu_patterns)
    if not is_feishu:
        return url
    
    # 嵌入优化参数
    embed_params = {
        'hideHeader': '1',      # 隐藏头部（包含"进入原应用"按钮）
        'hideSidebar': '1',     # 隐藏侧边栏
        'vc': 'true',           # 隐藏新增视图，工具栏上移
    }
    
    # 解析 URL 并添加参数
    from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
    
    parsed = urlparse(url)
    existing_params = parse_qs(parsed.query)
    
    # 合并参数（不覆盖已有参数，用户可能已手动添加）
    for key, value in embed_params.items():
        if key not in existing_params:
            existing_params[key] = [value]
    
    # 重建 URL
    new_query = urlencode(existing_params, doseq=True)
    new_url = urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        new_query,
        parsed.fragment
    ))
    
    return new_url


def get_client_ip(request) -> str:
    """获取客户端IP（已禁用，合规要求不再收集IP地址）"""
    # 根据《个人信息保护法》，IP地址属于个人信息
    # 本项目已决定不收集用户IP地址
    return ""  # 返回空字符串


# ==================== 验证 API ====================

@app.post("/api/validate", response_model=ValidateResponse)
async def validate_card_key(request: ValidateRequest, fastapi_request: Request):
    """
    验证卡密 API
    - 检查卡密是否存在
    - 检查状态是否有效
    - 检查是否过期
    - 检查设备数量限制（最多5台）
    - 记录访问日志（含行为数据）
    """
    client = None
    card_key = request.card_key.strip().upper()
    device_id = request.device_id or "unknown"
    # IP地址、User-Agent收集已禁用（合规要求）
    
    try:
        if not card_key:
            return ValidateResponse(can_access=False, msg="请输入卡密")

        logger.info(f"验证卡密: {card_key}, 设备: {device_id}")

        client = get_supabase_client()

        # 查询卡密
        response = client.table('card_keys_table').select('*').eq('key_value', card_key).execute()

        if not response.data:
            log_access(client, None, card_key, False, "卡密不存在", device_id)
            return ValidateResponse(can_access=False, msg="卡密不存在")

        card_data = response.data[0]
        card_id = card_data.get('id')
        sales_channel = card_data.get('sales_channel', '')
        
        # 检查是否首次访问（该卡密是否有成功访问记录）
        is_first_access = False
        existing_logs = client.table('access_logs').select('id').eq('key_value', card_key).eq('success', True).limit(1).execute()
        if not existing_logs.data:
            is_first_access = True

        # 检查状态 (1=有效, 0=无效)
        if card_data.get('status') != 1:
            log_access(client, card_id, card_key, False, "卡密已失效", device_id, sales_channel, is_first_access)
            return ValidateResponse(can_access=False, msg="卡密已失效")

        # 检查过期时间
        expire_at = card_data.get('expire_at')
        if expire_at:
            expire_time = datetime.fromisoformat(expire_at.replace('Z', '+00:00'))
            if datetime.now(expire_time.tzinfo) > expire_time:
                log_access(client, card_id, card_key, False, "卡密已过期", device_id, sales_channel, is_first_access)
                return ValidateResponse(can_access=False, msg="卡密已过期")

        # 检查设备限制（最多5台设备）
        max_devices = card_data.get('max_devices', 5)
        devices_json = card_data.get('devices', '[]')
        
        try:
            bound_devices = json.loads(devices_json) if devices_json else []
        except:
            bound_devices = []
        
        # 检查设备是否已绑定
        device_already_bound = device_id in bound_devices
        
        if not device_already_bound:
            # 新设备，检查是否达到设备限制
            if len(bound_devices) >= max_devices:
                log_access(client, card_id, card_key, False, f"设备数量已达上限({max_devices}台)", device_id, sales_channel, is_first_access)
                return ValidateResponse(can_access=False, msg=f"该卡密已在{max_devices}台设备上使用，无法在新设备登录")
            
            # 添加新设备
            bound_devices.append(device_id)
            client.table('card_keys_table').update({
                "devices": json.dumps(bound_devices),
                "last_used_at": datetime.now().isoformat()
            }).eq('id', card_id).execute()
        else:
            # 已绑定设备，只更新最后使用时间
            client.table('card_keys_table').update({
                "last_used_at": datetime.now().isoformat()
            }).eq('id', card_id).execute()

        # 记录成功日志（含行为数据）
        log_access(client, card_id, card_key, True, "验证成功", device_id, sales_channel, is_first_access)

        feishu_url = card_data.get('feishu_url', '')
        feishu_password = card_data.get('feishu_password', '')
        
        # 添加飞书官方嵌入参数，优化嵌入体验
        if feishu_url:
            feishu_url = add_feishu_embed_params(feishu_url)

        logger.info(f"验证成功: {card_key}, 设备: {device_id}, 已绑定设备数: {len(bound_devices)}, 首次访问: {is_first_access}")

        return ValidateResponse(
            can_access=True,
            url=feishu_url,
            password=feishu_password,
            msg="验证成功"
        )

    except Exception as e:
        logger.error(f"验证失败: {str(e)}")
        if client:
            log_access(client, None, card_key, False, f"系统错误: {str(e)}", device_id)
        return ValidateResponse(can_access=False, msg="系统错误，请稍后重试")


def log_access(client, card_key_id, key_value, success, error_msg, device_id=None, sales_channel=None, is_first_access=False):
    """记录访问日志
    
    注意：根据《个人信息保护法》合规要求，不再收集IP地址、User-Agent、设备类型
    """
    try:
        now = datetime.now()
        
        # 基本日志数据
        # 注意：已移除 ip_address、user_agent、device_type 字段（合规要求）
        log_data = {
            "card_key_id": card_key_id,
            "key_value": key_value,
            "success": success,
            "error_msg": error_msg if not success else None,
            "access_time": now.isoformat(),
            "access_date": now.strftime('%Y-%m-%d'),
            "access_hour": now.hour,
            "is_first_access": is_first_access,
            "sales_channel": sales_channel
        }
        
        client.table('access_logs').insert(log_data).execute()
        logger.info(f"访问日志记录成功: {key_value}")
                
    except Exception as e:
        logger.error(f"记录日志失败: {str(e)}")


# ==================== 管理后台 API ====================

@app.get("/api/admin/cards")
async def get_card_keys(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    activate_status: Optional[str] = None,  # valid, activated, disabled
    feishu_url: Optional[str] = None,
    created_start: Optional[str] = None,
    created_end: Optional[str] = None,
    expire_days: Optional[str] = None,
    sale_status: Optional[str] = None,
    device_filter: Optional[str] = None,
    sales_channel: Optional[str] = None  # 销售渠道筛选
):
    """获取卡密列表"""
    try:
        client = get_supabase_client()
        
        query = client.table('card_keys_table').select('*', count='exact')
        
        # 搜索支持卡密、备注、订单号
        if search:
            query = query.or_(f"key_value.ilike.%{search}%,user_note.ilike.%{search}%,order_id.ilike.%{search}%")
        
        # 激活状态筛选（动态计算）
        # - valid（有效）：未使用过且销售状态正常
        # - activated（已激活）：已使用过且状态正常  
        # - disabled（已停用）：退款或有纠纷
        if activate_status:
            if activate_status == 'disabled':
                # 已停用：退款或有纠纷
                query = query.in_('sale_status', ['refunded', 'disputed'])
            elif activate_status == 'valid':
                # 有效：未使用过且销售状态正常
                query = query.eq('devices', '[]').eq('used_count', 0)
                query = query.not_.in_('sale_status', ['refunded', 'disputed'])
            elif activate_status == 'activated':
                # 已激活：已使用过且状态正常（需要在应用层过滤）
                # 先获取已使用过的记录，然后在应用层过滤
                query = query.not_.in_('sale_status', ['refunded', 'disputed'])
                # 使用 or 条件：devices != '[]' OR used_count > 0
                query = query.or_("devices.neq.[],used_count.gt.0")
        
        if feishu_url:
            query = query.eq('feishu_url', feishu_url)
        
        if sales_channel:
            query = query.eq('sales_channel', sales_channel)
        
        if sale_status:
            # 映射中文值到英文
            sale_status_map = {
                '未销售': 'unsold',
                '已售出': 'sold',
                '已核销': 'used',
                '已退款': 'refunded',
                '有纠纷': 'disputed'
            }
            mapped_status = sale_status_map.get(sale_status, sale_status)
            query = query.eq('sale_status', mapped_status)
        
        if created_start:
            query = query.gte('bstudio_create_time', created_start)
        if created_end:
            query = query.lte('bstudio_create_time', created_end + 'T23:59:59')
        
        # 绑定设备筛选（按设备数量）需要在应用层处理
        need_device_filter = False
        device_count_filter = 0
        if device_filter:
            try:
                device_count_filter = int(device_filter)
                if device_count_filter == 0:
                    # 0台：空数组，可以用精确匹配
                    query = query.eq('devices', '[]')
                else:
                    # 其他数量：需要在应用层过滤
                    need_device_filter = True
            except ValueError:
                pass
        
        # 过期时间筛选（未来天数）
        if expire_days:
            now = datetime.now()
            if expire_days == 'expired':
                # 已过期：过期时间不为空且小于当前时间
                query = query.not_.is_('expire_at', 'null').lt('expire_at', now.isoformat())
            elif expire_days == 'permanent':
                # 永久有效：过期时间为空
                query = query.is_('expire_at', 'null')
            else:
                # 未来N天内过期：过期时间在当前时间和N天后之间
                try:
                    days = int(expire_days)
                    future_date = (now + timedelta(days=days)).isoformat()
                    query = query.not_.is_('expire_at', 'null').gte('expire_at', now.isoformat()).lte('expire_at', future_date)
                except ValueError:
                    pass
        
        # 如果需要在应用层过滤设备数量，先获取所有数据再过滤
        if need_device_filter:
            # 获取所有匹配的数据
            response = query.order('id', desc=True).execute()
            all_data = response.data
            
            # 在应用层过滤设备数量
            filtered_data = []
            for card in all_data:
                try:
                    devices = json.loads(card.get('devices', '[]'))
                    if len(devices) == device_count_filter:
                        filtered_data.append(card)
                except:
                    pass
            
            # 手动分页
            total = len(filtered_data)
            total_pages = (total + page_size - 1) // page_size if total else 0
            start = (page - 1) * page_size
            end = start + page_size
            paginated_data = filtered_data[start:end]
            
            return {
                "success": True,
                "data": paginated_data,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages
            }
        
        start = (page - 1) * page_size
        end = start + page_size - 1
        
        response = query.range(start, end).order('id', desc=True).execute()
        
        return {
            "success": True,
            "data": response.data,
            "total": response.count,
            "page": page,
            "page_size": page_size,
            "total_pages": (response.count + page_size - 1) // page_size if response.count else 0
        }
        
    except Exception as e:
        logger.error(f"获取卡密列表失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.get("/api/admin/cards/by-ids")
async def get_cards_by_ids(ids: str = Query(..., description="逗号分隔的ID列表")):
    """根据ID列表获取卡密详情"""
    try:
        client = get_supabase_client()
        
        id_list = [int(x.strip()) for x in ids.split(',') if x.strip()]
        if not id_list:
            return {"success": False, "msg": "请提供有效的ID列表"}
        
        response = client.table('card_keys_table').select('*').in_('id', id_list).execute()
        
        return {"success": True, "data": response.data}
        
    except Exception as e:
        logger.error(f"根据ID获取卡密失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.post("/api/admin/cards/batch-update")
async def batch_update_cards(request: BatchUpdateRequest):
    """批量更新筛选结果"""
    try:
        client = get_supabase_client()
        
        # 判断使用ids还是filters
        if request.ids and len(request.ids) > 0:
            # 使用指定的ID列表
            affected_ids = [int(id) for id in request.ids]
        elif request.filters:
            # 构建查询条件
            query = client.table('card_keys_table').select('id')
            
            filters = request.filters
            
            # 激活状态筛选
            activate_status = filters.get('activate_status')
            if activate_status and activate_status != '':
                if activate_status == 'disabled':
                    query = query.in_('sale_status', ['refunded', 'disputed'])
                elif activate_status == 'valid':
                    query = query.eq('devices', '[]').eq('used_count', 0)
                    query = query.not_.in_('sale_status', ['refunded', 'disputed'])
                elif activate_status == 'activated':
                    query = query.not_.in_('sale_status', ['refunded', 'disputed'])
                    query = query.or_("devices.neq.[],used_count.gt.0")
            
            if filters.get('sale_status') and filters.get('sale_status') != '':
                # 映射中文值到英文
                sale_status_map = {
                    '未销售': 'unsold',
                    '已售出': 'sold',
                    '已核销': 'used',
                    '已退款': 'refunded',
                    '有纠纷': 'disputed'
                }
                mapped_status = sale_status_map.get(filters['sale_status'], filters['sale_status'])
                query = query.eq('sale_status', mapped_status)
            
            if filters.get('feishu_url') and filters.get('feishu_url') != '':
                query = query.eq('feishu_url', filters['feishu_url'])
            
            # 销售渠道筛选
            if filters.get('sales_channel') and filters.get('sales_channel') != '':
                query = query.eq('sales_channel', filters['sales_channel'])
            
            # 绑定设备筛选（按设备数量）
            device_filter = filters.get('device_filter')
            need_device_filter = False
            device_count_filter = 0
            if device_filter and device_filter != '':
                try:
                    device_count_filter = int(device_filter)
                    if device_count_filter == 0:
                        query = query.eq('devices', '[]')
                    else:
                        need_device_filter = True
                except ValueError:
                    pass
            
            # 过期时间筛选（未来天数）
            expire_days = filters.get('expire_days')
            if expire_days and expire_days != '':
                now = datetime.now()
                if expire_days == 'expired':
                    query = query.not_.is_('expire_at', 'null').lt('expire_at', now.isoformat())
                elif expire_days == 'permanent':
                    query = query.is_('expire_at', 'null')
                else:
                    try:
                        days = int(expire_days)
                        future_date = (now + timedelta(days=days)).isoformat()
                        query = query.not_.is_('expire_at', 'null').gte('expire_at', now.isoformat()).lte('expire_at', future_date)
                    except ValueError:
                        pass
            
            if filters.get('search') and filters.get('search') != '':
                search = filters['search']
                query = query.or_(f"key_value.ilike.%{search}%,user_note.ilike.%{search}%,order_id.ilike.%{search}%")
            
            if filters.get('created_start') and filters.get('created_start') != '':
                query = query.gte('bstudio_create_time', filters['created_start'])
            if filters.get('created_end') and filters.get('created_end') != '':
                query = query.lte('bstudio_create_time', filters['created_end'] + 'T23:59:59')
            
            # 获取符合条件的记录
            response = query.execute()
            
            # 如果需要在应用层过滤设备数量
            if need_device_filter:
                filtered_data = []
                for card in response.data:
                    try:
                        devices = json.loads(card.get('devices', '[]'))
                        if len(devices) == device_count_filter:
                            filtered_data.append(card)
                    except:
                        pass
                affected_ids = [item['id'] for item in filtered_data]
            else:
                affected_ids = [item['id'] for item in response.data]
        else:
            return {"success": False, "msg": "请提供ids或filters参数"}
        
        affected_count = len(affected_ids)
        
        if affected_count == 0:
            return {"success": False, "msg": "没有符合条件的记录"}
        
        # 准备更新数据
        updates = request.updates
        update_data = {}
        
        if 'status' in updates and updates['status'] is not None:
            update_data['status'] = int(updates['status'])
        
        if 'sale_status' in updates and updates['sale_status']:
            update_data['sale_status'] = updates['sale_status']
            if updates['sale_status'] == 'sold':
                update_data['sold_at'] = datetime.now().isoformat()
            # 已退款/有纠纷时自动停用（如果没有明确设置status）
            if updates['sale_status'] in ['refunded', 'disputed'] and 'status' not in updates:
                update_data['status'] = 0
        
        if 'feishu_url' in updates:
            update_data['feishu_url'] = updates['feishu_url'] or ''
        
        if 'feishu_password' in updates:
            update_data['feishu_password'] = updates['feishu_password'] or ''
        
        if 'link_name' in updates:
            update_data['link_name'] = updates['link_name'] or ''
        
        if 'expire_at' in updates:
            update_data['expire_at'] = updates['expire_at'] or None
        
        if 'user_note' in updates:
            update_data['user_note'] = updates['user_note'] or ''
        
        if 'sales_channel' in updates:
            update_data['sales_channel'] = updates['sales_channel'] or ''
        
        if not update_data:
            return {"success": False, "msg": "没有需要更新的字段"}
        
        # 执行批量更新
        update_response = client.table('card_keys_table').update(update_data).in_('id', affected_ids).execute()
        
        # 记录操作日志
        log_data = {
            "operator": "admin",
            "operation_type": "batch_update",
            "filter_conditions": request.filters if request.filters else {"ids": request.ids},
            "affected_count": affected_count,
            "affected_ids": affected_ids,
            "update_fields": update_data,
            "remark": request.remark or ""
        }
        client.table('batch_operation_logs').insert(log_data).execute()
        
        logger.info(f"批量更新成功: 影响记录数={affected_count}, 更新字段={list(update_data.keys())}")
        
        return {
            "success": True,
            "msg": f"成功更新 {affected_count} 条记录",
            "affected_count": affected_count,
            "affected_ids": affected_ids[:100]  # 只返回前100个ID
        }
        
    except Exception as e:
        logger.error(f"批量更新失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.get("/api/admin/cards/count-by-filters")
async def count_by_filters(
    activate_status: Optional[str] = None,
    sale_status: Optional[str] = None,
    feishu_url: Optional[str] = None,
    expire_days: Optional[str] = None,
    device_filter: Optional[str] = None,
    search: Optional[str] = None,
    created_start: Optional[str] = None,
    created_end: Optional[str] = None
):
    """根据筛选条件统计记录数"""
    try:
        client = get_supabase_client()
        
        # 如果需要设备数量筛选，需要选择devices字段
        need_device_filter = False
        device_count_filter = 0
        if device_filter and device_filter != '':
            try:
                device_count_filter = int(device_filter)
                if device_count_filter != 0:
                    need_device_filter = True
            except ValueError:
                pass
        
        # 根据是否需要应用层过滤选择字段
        if need_device_filter:
            query = client.table('card_keys_table').select('id,devices', count='exact')
        else:
            query = client.table('card_keys_table').select('id', count='exact')
        
        # 激活状态筛选
        if activate_status and activate_status != '':
            if activate_status == 'disabled':
                query = query.in_('sale_status', ['refunded', 'disputed'])
            elif activate_status == 'valid':
                query = query.eq('devices', '[]').eq('used_count', 0)
                query = query.not_.in_('sale_status', ['refunded', 'disputed'])
            elif activate_status == 'activated':
                query = query.not_.in_('sale_status', ['refunded', 'disputed'])
                query = query.or_("devices.neq.[],used_count.gt.0")
        
        if sale_status and sale_status != '':
            # 映射中文值到英文
            sale_status_map = {
                '未销售': 'unsold',
                '已售出': 'sold',
                '已核销': 'used',
                '已退款': 'refunded',
                '有纠纷': 'disputed'
            }
            mapped_status = sale_status_map.get(sale_status, sale_status)
            query = query.eq('sale_status', mapped_status)
        
        if feishu_url and feishu_url != '':
            query = query.eq('feishu_url', feishu_url)
        
        # 绑定设备筛选（按设备数量）- 注意need_device_filter已在前面定义
        if device_filter and device_filter != '':
            try:
                device_count_filter = int(device_filter)
                if device_count_filter == 0:
                    query = query.eq('devices', '[]')
                # else: need_device_filter已经在前面设为True
            except ValueError:
                pass
        
        # 过期时间筛选（未来天数）
        if expire_days and expire_days != '':
            now = datetime.now()
            if expire_days == 'expired':
                query = query.not_.is_('expire_at', 'null').lt('expire_at', now.isoformat())
            elif expire_days == 'permanent':
                query = query.is_('expire_at', 'null')
            else:
                try:
                    days = int(expire_days)
                    future_date = (now + timedelta(days=days)).isoformat()
                    query = query.not_.is_('expire_at', 'null').gte('expire_at', now.isoformat()).lte('expire_at', future_date)
                except ValueError:
                    pass
        
        if search and search != '':
            query = query.or_(f"key_value.ilike.%{search}%,user_note.ilike.%{search}%,order_id.ilike.%{search}%")
        
        if created_start and created_start != '':
            query = query.gte('bstudio_create_time', created_start)
        if created_end and created_end != '':
            query = query.lte('bstudio_create_time', created_end + 'T23:59:59')
        
        # 如果需要在应用层过滤设备数量
        if need_device_filter:
            response = query.execute()
            count = 0
            for card in response.data:
                try:
                    devices = json.loads(card.get('devices', '[]'))
                    if len(devices) == device_count_filter:
                        count += 1
                except:
                    pass
            return {"success": True, "count": count}
        
        response = query.execute()
        
        return {"success": True, "count": response.count}
        
    except Exception as e:
        logger.error(f"统计记录数失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.get("/api/admin/operation-logs")
async def get_operation_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    operation_type: Optional[str] = None,
    search: Optional[str] = None
):
    """获取操作日志列表"""
    try:
        client = get_supabase_client()
        
        query = client.table('batch_operation_logs').select('*', count='exact')
        
        if operation_type:
            query = query.eq('operation_type', operation_type)
        
        if search:
            query = query.ilike('operator', f'%{search}%')
        
        start = (page - 1) * page_size
        end = start + page_size - 1
        
        response = query.range(start, end).order('id', desc=True).execute()
        
        # 格式化返回数据
        for item in response.data:
            if item.get('created_at'):
                item['created_at'] = item['created_at'].replace('T', ' ').split('+')[0].split('.')[0]
        
        return {
            "success": True,
            "data": response.data,
            "total": response.count,
            "page": page,
            "page_size": page_size,
            "total_pages": (response.count + page_size - 1) // page_size if response.count else 0
        }
        
    except Exception as e:
        logger.error(f"获取操作日志失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.get("/api/admin/operation-logs/{log_id}")
async def get_operation_log(log_id: int):
    """获取单条操作日志详情"""
    try:
        client = get_supabase_client()
        response = client.table('batch_operation_logs').select('*').eq('id', log_id).execute()
        
        if not response.data:
            return {"success": False, "msg": "日志不存在"}
        
        log = response.data[0]
        if log.get('created_at'):
            log['created_at'] = log['created_at'].replace('T', ' ').split('+')[0].split('.')[0]
        
        return {"success": True, "data": log}
        
    except Exception as e:
        logger.error(f"获取操作日志详情失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.get("/api/admin/cards/filter-options")
async def get_filter_options(
    status: Optional[str] = None,
    sale_status: Optional[str] = None,
    feishu_url: Optional[str] = None,
    expire_status: Optional[str] = None,
    search: Optional[str] = None,
    created_start: Optional[str] = None,
    created_end: Optional[str] = None,
    exclude_field: Optional[str] = None
):
    """
    获取基于当前筛选条件的各字段可选值
    - exclude_field: 排除的字段（用于获取其他字段选项时，不应用该字段的筛选）
    """
    try:
        client = get_supabase_client()
        
        # 构建基础查询（排除当前要获取的字段）
        query = client.table('card_keys_table').select('status, sale_status, feishu_url')
        
        # 应用筛选条件（排除当前字段）
        if status is not None and status != '' and exclude_field != 'status':
            query = query.eq('status', int(status))
        
        if sale_status and sale_status != '' and exclude_field != 'sale_status':
            query = query.eq('sale_status', sale_status)
        
        if feishu_url and feishu_url != '' and exclude_field != 'feishu_url':
            query = query.eq('feishu_url', feishu_url)
        
        if expire_status and expire_status != '' and exclude_field != 'expire_status':
            now = datetime.now().isoformat()
            if expire_status == 'expired':
                query = query.not_.is_('expire_at', 'null').lt('expire_at', now)
            elif expire_status == 'not_expired':
                query = query.or_(f"expire_at.is.null,expire_at.gte.{now}")
            elif expire_status == 'permanent':
                query = query.is_('expire_at', 'null')
        
        if search and search != '' and exclude_field != 'search':
            query = query.or_(f"key_value.ilike.%{search}%,user_note.ilike.%{search}%")
        
        if created_start and created_start != '' and exclude_field != 'created_start':
            query = query.gte('bstudio_create_time', created_start)
        if created_end and created_end != '' and exclude_field != 'created_end':
            query = query.lte('bstudio_create_time', created_end + 'T23:59:59')
        
        response = query.execute()
        
        # 统计各字段的可选值
        status_count = {}
        sale_status_count = {}
        feishu_url_count = {}
        
        for item in response.data:
            # 激活状态
            s = item.get('status')
            status_key = str(s) if s is not None else ''
            status_count[status_key] = status_count.get(status_key, 0) + 1
            
            # 销售状态
            ss = item.get('sale_status') or ''
            sale_status_count[ss] = sale_status_count.get(ss, 0) + 1
            
            # 飞书链接
            fu = item.get('feishu_url') or ''
            feishu_url_count[fu] = feishu_url_count.get(fu, 0) + 1
        
        return {
            "success": True,
            "data": {
                "status": status_count,  # {"1": 10, "0": 5}
                "sale_status": sale_status_count,  # {"unsold": 3, "sold": 8, ...}
                "feishu_url": feishu_url_count,
                "total": len(response.data)
            }
        }
        
    except Exception as e:
        logger.error(f"获取筛选选项失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.get("/api/admin/cards/feishu-urls")
async def get_feishu_urls():
    """获取所有不同的飞书链接列表（用于筛选下拉）"""
    try:
        client = get_supabase_client()
        
        # 获取所有记录的飞书链接和链接名称
        response = client.table('card_keys_table').select('feishu_url,link_name').execute()
        
        # 统计每个链接的数量和名称
        url_info = {}
        for item in response.data:
            url = item.get('feishu_url') or ''
            name = item.get('link_name') or ''
            key = url if url else '(空)'
            if key not in url_info:
                url_info[key] = {"url": url, "name": name, "count": 0}
            url_info[key]["count"] += 1
            # 如果有名称，更新名称
            if name and not url_info[key]["name"]:
                url_info[key]["name"] = name
        
        # 转换为列表并按数量排序
        urls = list(url_info.values())
        urls.sort(key=lambda x: x['count'], reverse=True)
        
        return {"success": True, "data": urls}
        
    except Exception as e:
        logger.error(f"获取飞书链接列表失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.get("/api/admin/cards/sales-channels")
async def get_sales_channels():
    """获取所有不同的销售渠道列表（用于筛选下拉）"""
    try:
        client = get_supabase_client()
        
        # 获取所有记录的销售渠道
        response = client.table('card_keys_table').select('sales_channel').execute()
        
        # 统计每个渠道的数量
        channel_count = {}
        for item in response.data:
            channel = item.get('sales_channel') or ''
            if channel:
                channel_count[channel] = channel_count.get(channel, 0) + 1
        
        # 转换为列表并按数量排序
        channels = [{"channel": k, "count": v} for k, v in channel_count.items()]
        channels.sort(key=lambda x: x['count'], reverse=True)
        
        return {"success": True, "data": channels}
        
    except Exception as e:
        logger.error(f"获取销售渠道列表失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.get("/api/admin/cards/export")
async def export_cards(
    ids: Optional[str] = None,
    status: Optional[int] = None,
    format: str = "csv"
):
    """
    导出卡密
    - ids: 逗号分隔的ID列表，不传则导出全部
    - format: csv 或 txt
    - 适配阿奇索平台格式（卡号,密码）
    """
    try:
        client = get_supabase_client()
        
        query = client.table('card_keys_table').select('key_value,feishu_password,status,user_note')
        
        if ids:
            id_list = [int(x) for x in ids.split(',')]
            query = query.in_('id', id_list)
        elif status is not None:
            query = query.eq('status', status)
        
        response = query.order('id', desc=True).execute()
        
        if not response.data:
            return {"success": False, "msg": "没有可导出的数据"}
        
        # 生成 CSV
        output = io.StringIO()
        writer = csv.writer(output)
        
        # 阿奇索格式：卡号,密码（无表头）
        for card in response.data:
            writer.writerow([
                card['key_value'],
                card['feishu_password'] or ''
            ])
        
        output.seek(0)
        
        # 返回文件流
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=cards_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            }
        )
        
    except Exception as e:
        logger.error(f"导出卡密失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.get("/api/admin/cards/sale-status-template")
async def download_sale_status_template():
    """下载销售状态导入模板"""
    try:
        output = io.StringIO()
        writer = csv.writer(output)
        
        # 模板表头
        writer.writerow(['卡密', '订单号', '销售状态', '销售渠道'])
        # 示例行 - 包含所有销售状态
        writer.writerow(['CSS-XXXX-XXXX-XXXX', '', '未售出', ''])
        writer.writerow(['CSS-YYYY-YYYY-YYYY', 'ORDER123456', '已售出', '小红书'])
        writer.writerow(['CSS-ZZZZ-ZZZZ-ZZZZ', 'ORDER789012', '已退款', '淘宝'])
        writer.writerow(['CSS-WWWW-WWWW-WWWW', 'ORDER111222', '有纠纷', '抖音'])
        
        output.seek(0)
        # UTF-8 BOM + 内容，确保 Excel 正确识别中文编码
        bom = b'\xef\xbb\xbf'
        content = bom + output.getvalue().encode('utf-8')
        
        return StreamingResponse(
            iter([content]),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f"attachment; filename=sale_status_template.csv"
            }
        )
        
    except Exception as e:
        logger.error(f"下载模板失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.post("/api/admin/cards/import-sale-status")
async def import_sale_status(file: UploadFile = File(...)):
    """
    批量导入销售状态和销售渠道
    - 读取CSV文件，匹配卡密更新销售状态和销售渠道
    - 已退款/有纠纷的卡密自动停用
    """
    try:
        client = get_supabase_client()
        
        # 读取上传的CSV文件，尝试多种编码
        content = await file.read()
        
        # 尝试多种编码解码
        text = None
        encodings = ['utf-8-sig', 'utf-8', 'gbk', 'gb2312', 'gb18030']
        for encoding in encodings:
            try:
                text = content.decode(encoding)
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
        
        if text is None:
            return {"success": False, "msg": "无法识别文件编码，请确保文件为 UTF-8 或 GBK 编码"}
        
        # 检查是否有列名行
        lines = text.strip().split('\n')
        first_line = lines[0] if lines else ''
        has_header = '卡密' in first_line or '订单号' in first_line or '销售状态' in first_line
        
        reader = csv.DictReader(io.StringIO(text))
        
        # 获取实际的列名并标准化（去除空格等）
        if reader.fieldnames:
            field_map = {name.strip(): name for name in reader.fieldnames}
        else:
            field_map = {}
        
        logger.info(f"CSV列名: {reader.fieldnames}, 标准化后: {list(field_map.keys())}, 是否有表头: {has_header}")
        
        # 状态映射（支持"已销售"作为"已售出"的别名）
        status_map = {
            '未售出': 'unsold',
            '已售出': 'sold',
            '已销售': 'sold',  # 别名
            '已退款': 'refunded',
            '有纠纷': 'disputed'
        }
        
        updated_count = 0
        deactivated_count = 0
        not_found = []
        skip_count = 0
        invalid_status_count = 0
        
        # 如果没有标准列名，按位置解析
        if not has_header:
            # 重新读取，使用位置索引
            reader_list = list(csv.reader(io.StringIO(text)))
            logger.info(f"无表头模式，共{len(reader_list)}行数据")
            
            for row in reader_list:
                if len(row) < 3:
                    skip_count += 1
                    continue
                
                key_value = row[0].strip().upper()
                order_id = row[1].strip() if len(row) > 1 else ''
                sale_status_text = row[2].strip() if len(row) > 2 else ''
                sales_channel = row[3].strip() if len(row) > 3 else ''
                
                logger.info(f"无表头处理行: 卡密={key_value}, 订单号={order_id}, 销售状态={sale_status_text}, 销售渠道={sales_channel}")
                
                if not key_value or not sale_status_text:
                    skip_count += 1
                    continue
                
                sale_status = status_map.get(sale_status_text)
                if not sale_status:
                    invalid_status_count += 1
                    logger.warning(f"无效的销售状态: {sale_status_text}")
                    continue
                
                # 查找卡密
                find_response = client.table('card_keys_table').select('id, status').eq('key_value', key_value).execute()
                if not find_response.data:
                    not_found.append(key_value)
                    continue
                
                card = find_response.data[0]
                card_id = card['id']
                current_status = card['status']
                
                # 准备更新数据
                update_data = {
                    'sale_status': sale_status,
                    'order_id': order_id or None
                }
                
                # 销售渠道（如果有）
                if sales_channel:
                    update_data['sales_channel'] = sales_channel
                
                # 已售出时记录时间
                if sale_status == 'sold':
                    update_data['sold_at'] = datetime.now().isoformat()
                
                # 已退款/有纠纷时自动停用
                if sale_status in ['refunded', 'disputed'] and current_status == 1:
                    update_data['status'] = 0
                    deactivated_count += 1
                
                # 更新卡密
                client.table('card_keys_table').update(update_data).eq('id', card_id).execute()
                updated_count += 1
        else:
            for row in reader:
                # 使用标准化列名获取数据
                raw_key = row.get(field_map.get('卡密', '卡密'), '') or row.get('卡密', '')
                raw_order = row.get(field_map.get('订单号', '订单号'), '') or row.get('订单号', '')
                raw_status = row.get(field_map.get('销售状态', '销售状态'), '') or row.get('销售状态', '')
                raw_channel = row.get(field_map.get('销售渠道', '销售渠道'), '') or row.get('销售渠道', '')
                
                key_value = raw_key.strip().upper()
                order_id = raw_order.strip()
                sale_status_text = raw_status.strip()
                sales_channel = raw_channel.strip()
                
                logger.info(f"处理行: 卡密={key_value}, 订单号={order_id}, 销售状态={sale_status_text}, 销售渠道={sales_channel}")
                
                if not key_value or not sale_status_text:
                    skip_count += 1
                    logger.info(f"跳过空数据行: key_value={key_value}, sale_status_text={sale_status_text}")
                    continue
                
                sale_status = status_map.get(sale_status_text)
                if not sale_status:
                    invalid_status_count += 1
                    logger.warning(f"无效的销售状态: {sale_status_text}")
                    continue
                
                # 查找卡密
                find_response = client.table('card_keys_table').select('id, status').eq('key_value', key_value).execute()
                if not find_response.data:
                    not_found.append(key_value)
                    continue
                
                card = find_response.data[0]
                card_id = card['id']
                current_status = card['status']
                
                # 准备更新数据
                update_data = {
                    'sale_status': sale_status,
                    'order_id': order_id or None
                }
                
                # 销售渠道（如果有）
                if sales_channel:
                    update_data['sales_channel'] = sales_channel
                
                # 已售出时记录时间
                if sale_status == 'sold':
                    update_data['sold_at'] = datetime.now().isoformat()
                
                # 已退款/有纠纷时自动停用
                if sale_status in ['refunded', 'disputed'] and current_status == 1:
                    update_data['status'] = 0  # 停用
                    deactivated_count += 1
                
                # 更新卡密
                client.table('card_keys_table').update(update_data).eq('id', card_id).execute()
                updated_count += 1
        
        result_msg = f"成功更新 {updated_count} 条记录"
        if deactivated_count > 0:
            result_msg += f"，其中 {deactivated_count} 条已自动停用"
        if not_found:
            result_msg += f"，{len(not_found)} 条卡密未找到"
        if skip_count > 0:
            result_msg += f"，{skip_count} 条数据为空被跳过"
        if invalid_status_count > 0:
            result_msg += f"，{invalid_status_count} 条销售状态无效"
        
        return {
            "success": True,
            "msg": result_msg,
            "updated": updated_count,
            "deactivated": deactivated_count,
            "not_found": not_found[:10],  # 只返回前10条未找到的
            "skipped": skip_count,
            "invalid_status": invalid_status_count
        }
        
    except Exception as e:
        logger.error(f"导入销售状态失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.get("/api/admin/cards/{card_id}")
async def get_card_key(card_id: int):
    """获取单个卡密"""
    try:
        client = get_supabase_client()
        response = client.table('card_keys_table').select('*').eq('id', card_id).execute()
        
        if not response.data:
            return {"success": False, "msg": "卡密不存在"}
        
        return {"success": True, "data": response.data[0]}
        
    except Exception as e:
        logger.error(f"获取卡密失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.post("/api/admin/cards")
async def create_card_key(card: CardKeyCreate):
    """创建单个卡密"""
    try:
        client = get_supabase_client()
        
        # 检查卡密是否已存在
        existing = client.table('card_keys_table').select('id').eq('key_value', card.key_value.upper()).execute()
        if existing.data:
            return {"success": False, "msg": "卡密已存在"}
        
        # 计算过期时间
        expire_at = None
        if card.expire_days:
            expire_at = (datetime.now() + timedelta(days=card.expire_days)).isoformat()
        
        data = {
            "key_value": card.key_value.upper(),
            "status": card.status,
            "user_note": card.user_note or "",
            "feishu_url": card.feishu_url or "",
            "feishu_password": card.feishu_password or "",
            "link_name": card.link_name or "",
            "sys_platform": "卡密系统",
            "uuid": str(uuid.uuid4()),
            "bstudio_create_time": datetime.now().isoformat(),
            "expire_at": expire_at,
            "max_uses": card.max_uses,
            "used_count": 0
        }
        
        response = client.table('card_keys_table').insert(data).execute()
        
        return {"success": True, "data": response.data[0], "msg": "创建成功"}
        
    except Exception as e:
        logger.error(f"创建卡密失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.post("/api/admin/cards/batch-generate")
async def batch_generate_cards(req: BatchGenerateRequest):
    """
    批量生成卡密
    - 生成指定数量的卡密
    - 自动设置过期时间和使用次数限制
    """
    try:
        if req.count < 1 or req.count > 1000:
            return {"success": False, "msg": "生成数量必须在 1-1000 之间"}
        
        client = get_supabase_client()
        
        # 直接使用传入的过期时间
        expire_at = req.expire_at
        
        # 批量生成卡密
        cards = []
        generated_keys = set()
        
        for _ in range(req.count):
            # 确保卡密不重复
            while True:
                key = generate_card_key(req.prefix)
                if key not in generated_keys:
                    generated_keys.add(key)
                    break
            
            cards.append({
                "key_value": key,
                "status": 1,
                "user_note": req.user_note,
                "feishu_url": req.feishu_url,
                "feishu_password": req.feishu_password,
                "link_name": req.link_name,
                "sys_platform": "卡密系统",
                "uuid": str(uuid.uuid4()),
                "bstudio_create_time": datetime.now().isoformat(),
                "expire_at": expire_at,
                "max_uses": req.max_uses,
                "used_count": 0,
                "sales_channel": req.sales_channel
            })
        
        # 批量插入
        response = client.table('card_keys_table').insert(cards).execute()
        
        return {
            "success": True,
            "data": response.data,
            "msg": f"成功生成 {len(response.data)} 个卡密"
        }
        
    except Exception as e:
        logger.error(f"批量生成卡密失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.put("/api/admin/cards/{card_id}")
async def update_card_key(card_id: int, card: CardKeyUpdate):
    """更新卡密"""
    try:
        client = get_supabase_client()
        
        update_data = {}
        if card.key_value is not None:
            existing = client.table('card_keys_table').select('id').eq('key_value', card.key_value.upper()).neq('id', card_id).execute()
            if existing.data:
                return {"success": False, "msg": "卡密已存在"}
            update_data["key_value"] = card.key_value.upper()
        if card.status is not None:
            update_data["status"] = card.status
        if card.user_note is not None:
            update_data["user_note"] = card.user_note
        if card.feishu_url is not None:
            update_data["feishu_url"] = card.feishu_url
        if card.feishu_password is not None:
            update_data["feishu_password"] = card.feishu_password
        if card.link_name is not None:
            update_data["link_name"] = card.link_name
        if card.expire_at is not None:
            update_data["expire_at"] = card.expire_at
        if card.max_uses is not None:
            update_data["max_uses"] = card.max_uses
        if card.sale_status is not None:
            update_data["sale_status"] = card.sale_status
            # 已售出时记录时间
            if card.sale_status == 'sold':
                update_data["sold_at"] = datetime.now().isoformat()
        if card.order_id is not None:
            update_data["order_id"] = card.order_id or None
        if card.sales_channel is not None:
            update_data["sales_channel"] = card.sales_channel
        
        response = client.table('card_keys_table').update(update_data).eq('id', card_id).execute()
        
        if not response.data:
            return {"success": False, "msg": "卡密不存在"}
        
        return {"success": True, "data": response.data[0], "msg": "更新成功"}
        
    except Exception as e:
        logger.error(f"更新卡密失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.delete("/api/admin/cards/{card_id}")
async def delete_card_key(card_id: int):
    """删除卡密"""
    try:
        client = get_supabase_client()
        
        # 先删除相关的访问日志记录
        client.table('access_logs').delete().eq('card_key_id', card_id).execute()
        
        # 再删除卡密
        response = client.table('card_keys_table').delete().eq('id', card_id).execute()
        
        if not response.data:
            return {"success": False, "msg": "卡密不存在"}
        
        return {"success": True, "msg": "删除成功"}
        
    except Exception as e:
        logger.error(f"删除卡密失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.post("/api/admin/cards/batch")
async def batch_operation(operation: BatchOperation):
    """批量操作"""
    try:
        client = get_supabase_client()
        
        if not operation.ids:
            return {"success": False, "msg": "请选择要操作的卡密"}
        
        if operation.action == "delete":
            # 先删除相关的访问日志记录
            client.table('access_logs').delete().in_('card_key_id', operation.ids).execute()
            # 再删除卡密
            response = client.table('card_keys_table').delete().in_('id', operation.ids).execute()
            return {"success": True, "msg": f"成功删除 {len(response.data)} 条记录"}
            
        elif operation.action == "activate":
            response = client.table('card_keys_table').update({"status": 1}).in_('id', operation.ids).execute()
            return {"success": True, "msg": f"成功激活 {len(response.data)} 条记录"}
            
        elif operation.action == "deactivate":
            response = client.table('card_keys_table').update({"status": 0}).in_('id', operation.ids).execute()
            return {"success": True, "msg": f"成功停用 {len(response.data)} 条记录"}
            
        elif operation.action == "update_url":
            if not operation.feishu_url:
                return {"success": False, "msg": "请提供飞书链接"}
            response = client.table('card_keys_table').update({
                "feishu_url": operation.feishu_url,
                "feishu_password": operation.feishu_password or ""
            }).in_('id', operation.ids).execute()
            return {"success": True, "msg": f"成功更新 {len(response.data)} 条记录"}
        
        return {"success": False, "msg": "未知操作类型"}
            
    except Exception as e:
        logger.error(f"批量操作失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.get("/api/admin/logs")
async def get_access_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    card_key_id: Optional[int] = None,
    success: Optional[bool] = None,
    search: Optional[str] = None,
    sale_status: Optional[str] = None
):
    """获取访问日志，关联卡密详细信息"""
    try:
        client = get_supabase_client()
        
        query = client.table('access_logs').select('*', count='exact')
        
        if card_key_id:
            query = query.eq('card_key_id', card_key_id)
        if success is not None:
            query = query.eq('success', success)
        if search:
            query = query.ilike('key_value', f'%{search}%')
        
        start = (page - 1) * page_size
        end = start + page_size - 1
        
        response = query.range(start, end).order('access_time', desc=True).execute()
        
        # 获取卡密详细信息
        logs = response.data
        if logs:
            # 提取所有key_value
            key_values = list(set(log.get('key_value') for log in logs if log.get('key_value')))
            if key_values:
                # 批量查询卡密详细信息
                cards_response = client.table('card_keys_table').select(
                    'key_value,user_note,sale_status,sales_channel,order_id,status,devices,max_devices,expire_at'
                ).in_('key_value', key_values).execute()
                
                # 构建key_value到卡密信息的映射
                card_map = {}
                for card in (cards_response.data or []):
                    card_map[card['key_value']] = card
                
                # 为每条日志添加详细信息
                for log in logs:
                    card_info = card_map.get(log.get('key_value', ''), {})
                    log['card_note'] = card_info.get('user_note', '')
                    log['sale_status'] = card_info.get('sale_status', '')
                    log['sales_channel'] = card_info.get('sales_channel', '')
                    log['order_id'] = card_info.get('order_id', '')
                    log['card_status'] = card_info.get('status', 1)
                    log['devices'] = card_info.get('devices', '[]')
                    log['max_devices'] = card_info.get('max_devices', 5)
                    log['expire_at'] = card_info.get('expire_at', '')
                
                # 如果有销售状态筛选，在应用层过滤
                if sale_status:
                    logs = [log for log in logs if log.get('sale_status') == sale_status]
        
        return {
            "success": True,
            "data": logs,
            "total": response.count,
            "page": page,
            "page_size": page_size
        }
        
    except Exception as e:
        logger.error(f"获取访问日志失败: {str(e)}")
        return {"success": False, "msg": str(e)}


# ==================== 管理员登录 API ====================

@app.post("/api/admin/login")
async def admin_login(request: LoginRequest, response: JSONResponse):
    """管理员登录"""
    if request.password != ADMIN_PASSWORD:
        logger.warning(f"登录失败: 密码错误")
        return {"success": False, "msg": "密码错误"}
    
    token = create_token()
    logger.info(f"管理员登录成功")
    
    # 设置 cookie
    response.set_cookie(
        key="admin_token",
        value=token,
        max_age=TOKEN_EXPIRE_HOURS * 3600,
        httponly=True,
        samesite="lax"
    )
    
    return {"success": True, "token": token}


@app.post("/api/admin/logout")
async def admin_logout(response: JSONResponse):
    """管理员登出"""
    response.delete_cookie("admin_token")
    return {"success": True}


# ==================== 行为数据上报 API ====================

class SessionReport(BaseModel):
    """会话上报请求"""
    card_key: str
    session_duration: int  # 停留时长（秒）
    content_loaded: bool  # 内容是否加载成功
    session_id: Optional[str] = None  # 会话ID


@app.post("/api/report/session")
async def report_session(request: SessionReport):
    """
    上报会话行为数据
    - 停留时长
    - 内容加载状态
    """
    try:
        client = get_supabase_client()
        
        card_key = request.card_key.strip().upper()
        
        # 更新最近一条访问日志
        # 查找该卡密最近的成功访问记录
        recent_log = client.table('access_logs').select('id').eq('key_value', card_key).eq('success', True).order('access_time', desc=True).limit(1).execute()
        
        if recent_log.data:
            log_id = recent_log.data[0]['id']
            update_data = {}
            
            if request.session_duration and request.session_duration > 0:
                update_data['session_duration'] = min(request.session_duration, 86400)  # 最大24小时
            
            if request.content_loaded is not None:
                update_data['content_loaded'] = request.content_loaded
            
            if request.session_id:
                update_data['session_id'] = request.session_id[:64]
            
            if update_data:
                client.table('access_logs').update(update_data).eq('id', log_id).execute()
                logger.info(f"上报会话数据: 卡密={card_key}, 时长={request.session_duration}s, 内容加载={request.content_loaded}")
        
        return {"success": True}
        
    except Exception as e:
        logger.error(f"上报会话数据失败: {str(e)}")
        return {"success": False, "msg": str(e)}


# ==================== 数据分析统计 API ====================

@app.get("/api/admin/analytics/overview")
async def get_analytics_overview(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
):
    """获取数据分析概览
    
    注意：完整统计需要先执行数据库迁移脚本 src/migrations/001_add_analytics_fields.sql
    如果新字段不存在，会使用 access_time 字段进行基础统计
    """
    try:
        client = get_supabase_client()
        
        # 默认最近7天
        if not end_date:
            end_date = datetime.now().strftime('%Y-%m-%d')
        if not start_date:
            start_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        
        # 尝试使用 access_date 字段查询（新字段）
        try:
            logs_response = client.table('access_logs').select('*').gte('access_date', start_date).lte('access_date', end_date).execute()
            logs = logs_response.data or []
        except Exception:
            # 如果 access_date 字段不存在，使用 access_time 字段
            logger.warning("access_date 字段不存在，使用 access_time 字段进行日期过滤")
            start_datetime = f"{start_date}T00:00:00"
            end_datetime = f"{end_date}T23:59:59"
            logs_response = client.table('access_logs').select('*').gte('access_time', start_datetime).lte('access_time', end_datetime).execute()
            logs = logs_response.data or []
        
        # 基础统计
        total_visits = len(logs)
        success_visits = len([l for l in logs if l.get('success')])
        
        # 计算平均停留时长（如果字段存在）
        durations = [l.get('session_duration', 0) for l in logs if l.get('session_duration')]
        avg_duration = sum(durations) / len(durations) if durations else 0
        
        # 新用户占比（如果字段存在）
        first_access_count = len([l for l in logs if l.get('is_first_access')])
        new_user_ratio = first_access_count / total_visits if total_visits > 0 else 0
        
        # 内容加载成功率（如果字段存在）
        content_loaded_logs = [l for l in logs if l.get('content_loaded') is not None]
        content_success = len([l for l in content_loaded_logs if l.get('content_loaded')])
        content_success_rate = content_success / len(content_loaded_logs) if content_loaded_logs else 0
        
        # 时段分布（如果字段存在）
        hour_dist = {}
        for log in logs:
            hour = log.get('access_hour')
            if hour is not None:
                hour_dist[hour] = hour_dist.get(hour, 0) + 1
        
        return {
            "success": True,
            "data": {
                "total_visits": total_visits,
                "success_visits": success_visits,
                "success_rate": success_visits / total_visits if total_visits > 0 else 0,
                "avg_duration": round(avg_duration),
                "new_user_ratio": round(new_user_ratio, 2),
                "content_success_rate": round(content_success_rate, 2),
                "hour_distribution": hour_dist
            }
        }
        
    except Exception as e:
        logger.error(f"获取分析概览失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.get("/api/admin/analytics/channels")
async def get_analytics_channels(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
):
    """获取渠道效果分析
    
    注意：完整统计需要先执行数据库迁移脚本 src/migrations/001_add_analytics_fields.sql
    如果新字段不存在，会使用 access_time 字段进行基础统计
    """
    try:
        client = get_supabase_client()
        
        # 默认最近7天
        if not end_date:
            end_date = datetime.now().strftime('%Y-%m-%d')
        if not start_date:
            start_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        
        # 尝试使用 access_date 字段查询（新字段）
        try:
            logs_response = client.table('access_logs').select('*').gte('access_date', start_date).lte('access_date', end_date).execute()
            logs = logs_response.data or []
        except Exception:
            # 如果 access_date 字段不存在，使用 access_time 字段
            logger.warning("access_date 字段不存在，使用 access_time 字段进行日期过滤")
            start_datetime = f"{start_date}T00:00:00"
            end_datetime = f"{end_date}T23:59:59"
            logs_response = client.table('access_logs').select('*').gte('access_time', start_datetime).lte('access_time', end_datetime).execute()
            logs = logs_response.data or []
        
        # 按渠道分组统计
        channel_stats = {}
        for log in logs:
            channel = log.get('sales_channel') or '未知渠道'
            if channel not in channel_stats:
                channel_stats[channel] = {
                    'visits': 0,
                    'success': 0,
                    'first_access': 0,
                    'total_duration': 0,
                    'duration_count': 0
                }
            
            channel_stats[channel]['visits'] += 1
            if log.get('success'):
                channel_stats[channel]['success'] += 1
            if log.get('is_first_access'):
                channel_stats[channel]['first_access'] += 1
            if log.get('session_duration'):
                channel_stats[channel]['total_duration'] += log.get('session_duration', 0)
                channel_stats[channel]['duration_count'] += 1
        
        # 计算各渠道指标
        result = []
        for channel, stats in channel_stats.items():
            result.append({
                'channel': channel,
                'visits': stats['visits'],
                'success': stats['success'],
                'success_rate': round(stats['success'] / stats['visits'], 2) if stats['visits'] > 0 else 0,
                'first_access': stats['first_access'],
                'avg_duration': round(stats['total_duration'] / stats['duration_count']) if stats['duration_count'] > 0 else 0
            })
        
        # 按访问量排序
        result.sort(key=lambda x: x['visits'], reverse=True)
        
        return {
            "success": True,
            "data": result
        }
        
    except Exception as e:
        logger.error(f"获取渠道分析失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.get("/api/admin/check-auth")
async def check_auth(request: Request):
    """检查登录状态"""
    token = get_token_from_request(request)
    if verify_token(token):
        return {"authenticated": True}
    return {"authenticated": False}


# ==================== 在线用户统计 API ====================

@app.get("/api/online-users")
async def get_online_users():
    """获取在线用户统计（用于前端协作者显示）"""
    try:
        client = get_supabase_client()
        
        # 获取总卡密数（有效状态的）
        total_response = client.table('card_keys_table').select('id', count='exact').eq('status', 1).execute()
        total_cards = total_response.count or 0
        
        # 获取最近5分钟内有访问记录的唯一卡密数
        five_min_ago = (datetime.now() - timedelta(minutes=5)).isoformat()
        
        # 查询最近访问日志中的唯一卡密
        logs_response = client.table('access_logs').select('key_value').gte('access_time', five_min_ago).eq('success', True).execute()
        
        # 统计唯一卡密数
        unique_keys = set()
        if logs_response.data:
            for log in logs_response.data:
                if log.get('key_value'):
                    unique_keys.add(log['key_value'])
        
        online_count = len(unique_keys)
        
        return {
            "success": True,
            "total_cards": total_cards,
            "online_count": online_count,
            "use_real_data": total_cards >= 20  # 总卡密数>=20时使用真实数据
        }
        
    except Exception as e:
        logger.error(f"获取在线用户失败: {str(e)}")
        return {"success": False, "total_cards": 0, "online_count": 0, "use_real_data": False}


# ==================== 静态文件服务 ====================

# 微信验证文件配置（可配置多个）
WECHAT_VERIFY_FILES = {
    "f6f3f1102e163b12197a863f1873b9b2.txt": "215382aa832da898a1c0ad9e2e48a96a909277a9",
}

@app.get("/")
async def serve_index():
    """服务首页"""
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path, media_type="text/html")
    raise HTTPException(status_code=404, detail="Index page not found")


@app.get("/admin")
async def serve_admin():
    """服务管理后台"""
    admin_path = os.path.join(STATIC_DIR, "admin.html")
    if os.path.exists(admin_path):
        return FileResponse(admin_path, media_type="text/html")
    raise HTTPException(status_code=404, detail="Admin page not found")


# 微信验证文件路由（放在具体路由之后）
@app.get("/{verify_file}")
async def serve_wechat_verify(verify_file: str):
    """服务微信验证文件（仅匹配微信验证文件格式）"""
    # 只处理符合微信验证文件格式的请求：32位十六进制.txt
    if re.match(r'^[a-f0-9]{32}\.txt$', verify_file):
        if verify_file in WECHAT_VERIFY_FILES:
            return PlainTextResponse(WECHAT_VERIFY_FILES[verify_file])
    raise HTTPException(status_code=404, detail="File not found")


# 挂载静态文件目录
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ==================== 健康检查 ====================

@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
