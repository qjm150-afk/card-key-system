"""
卡密验证系统 - 主入口
使用 FastAPI + Supabase 连接 Coze 内置数据库
"""

import os
import sys

# 确保模块导入路径正确（支持从任意目录运行）
_current_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_current_dir)
# 项目根目录和 src 目录都加入路径，支持 from storage.xxx 导入
for _p in [_parent_dir, _current_dir]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 加载环境变量
# ========================================
# 重要：防止本地配置覆盖生产环境变量
# ========================================
# 加载策略：
# 1. 如果已有生产环境变量（DATABASE_URL 或 COZE_SUPABASE_URL），跳过 .env.local
# 2. 只有在没有任何数据库配置时，才加载 .env.local（本地开发场景）
# 3. 这样即使 .env.local 被意外提交，也不会影响生产环境
from dotenv import load_dotenv
_env_local = os.path.join(_parent_dir, '.env.local')

# 检查是否已有生产环境数据库配置
_has_production_db = bool(
    os.getenv('DATABASE_URL') or 
    os.getenv('PGDATABASE_URL') or 
    os.getenv('COZE_SUPABASE_URL')
)

if _has_production_db:
    # 生产环境：不加载 .env.local，避免覆盖系统环境变量
    print(f"[ENV] Production database config detected, skipping .env.local")
    print(f"[ENV] DATABASE_URL = {'已设置' if os.getenv('DATABASE_URL') or os.getenv('PGDATABASE_URL') else '未设置'}")
    print(f"[ENV] COZE_SUPABASE_URL = {'已设置' if os.getenv('COZE_SUPABASE_URL') else '未设置'}")
elif os.path.exists(_env_local):
    # 本地开发：加载 .env.local（设置 LOCAL_DEV_MODE=true 使用 SQLite）
    load_dotenv(_env_local, override=True)
    print(f"[ENV] Loaded .env.local from {_env_local} (local dev mode)")
    print(f"[ENV] LOCAL_DEV_MODE = {os.getenv('LOCAL_DEV_MODE')}")
    print(f"[ENV] COZE_SUPABASE_URL = {'已设置' if os.getenv('COZE_SUPABASE_URL') else '未设置'}")
else:
    # 无任何配置
    print(f"[ENV] No .env.local and no production config, using defaults")

# 导入其他模块
import logging
import uuid
import secrets
import csv
import io
import json
import re
from datetime import datetime, timedelta
from typing import Optional, List
from urllib.parse import quote
from fastapi import FastAPI, HTTPException, Query, Request, File, UploadFile
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 创建 FastAPI 应用
app = FastAPI(title="卡密验证系统")

# 启动事件 - 打印启动日志和测试数据库连接
@app.on_event("startup")
async def startup_event():
    logger.info("=" * 50)
    logger.info("[STARTUP] 卡密验证系统启动中...")
    logger.info(f"[STARTUP] ENV - DATABASE_URL: {'已设置' if os.getenv('DATABASE_URL') or os.getenv('PGDATABASE_URL') else '未设置'}")
    logger.info(f"[STARTUP] ENV - COZE_SUPABASE_URL: {'已设置' if os.getenv('COZE_SUPABASE_URL') else '未设置'}")
    logger.info(f"[STARTUP] ENV - LOCAL_DEV_MODE: {os.getenv('LOCAL_DEV_MODE')}")
    
    try:
        # 测试数据库连接
        from storage.database.db_client import get_db_client, get_db_mode
        client, _ = get_db_client()
        db_mode = get_db_mode()
        logger.info(f"[STARTUP] 数据库模式: {db_mode}")
        logger.info(f"[STARTUP] 数据库客户端类型: {type(client).__name__}")
        
        # 测试查询
        result = client.table('card_keys_table').select('id', count='exact').limit(1).execute()
        logger.info(f"[STARTUP] 数据库连接成功，总记录数: {result.count}")
    except Exception as e:
        logger.error(f"[STARTUP] 数据库连接失败: {str(e)}")
    
    logger.info("=" * 50)

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


# ==================== 权限验证中间件 ====================
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

class AdminAuthMiddleware(BaseHTTPMiddleware):
    """管理员权限验证中间件"""
    
    # 不需要验证的路径
    PUBLIC_PATHS = [
        "/api/admin/login",
        "/api/admin/logout",
        "/api/admin/check-auth",
        "/api/validate",
        "/api/online-users",
        "/health",
    ]
    
    async def dispatch(self, request, call_next):
        path = request.url.path
        
        # 检查是否是需要验证的admin API
        if path.startswith("/api/admin") and path not in self.PUBLIC_PATHS:
            # 获取token
            token = None
            
            # 从 Authorization header 获取
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
            
            # 从 cookie 获取
            if not token:
                token = request.cookies.get("admin_token")
            
            # 验证token
            if not token or token not in VALID_TOKENS:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "未授权访问，请先登录"}
                )
            
            # 检查token是否过期
            if datetime.now() > VALID_TOKENS[token]:
                del VALID_TOKENS[token]
                return JSONResponse(
                    status_code=401,
                    content={"detail": "登录已过期，请重新登录"}
                )
        
        return await call_next(request)

# 添加中间件
app.add_middleware(AdminAuthMiddleware)


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


from fastapi import Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# HTTP Bearer 安全方案
security = HTTPBearer(auto_error=False)


async def get_current_admin(credentials: HTTPAuthorizationCredentials = Depends(security), request: Request = None):
    """验证管理员权限的依赖项"""
    # 首先尝试从 Authorization header 获取
    token = None
    if credentials:
        token = credentials.credentials
    # 如果没有，尝试从 cookie 获取
    if not token and request:
        token = request.cookies.get("admin_token")
    
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="未授权访问，请先登录")
    return token


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


def safe_log_operation(client, log_data: dict):
    """
    安全记录操作日志（失败不影响主操作）
    
    云端 Supabase 的 batch_operation_logs 表可能存在：
    1. 字段不完整（缺少 filter_conditions 等新字段）
    2. 主键序列不同步
    
    因此日志记录失败时只记录警告，不抛出异常
    """
    try:
        client.table('batch_operation_logs').insert(log_data).execute()
    except Exception as e:
        logger.warning(f"记录操作日志失败（不影响主操作）: {str(e)}")


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

        logger.info(f"[Validate] 验证卡密: {card_key}, 设备: {device_id}")

        # 获取数据库客户端
        try:
            client = get_supabase_client()
            logger.info(f"[Validate] 数据库客户端类型: {type(client).__name__}")
        except Exception as db_err:
            logger.error(f"[Validate] 获取数据库客户端失败: {str(db_err)}")
            return ValidateResponse(can_access=False, msg="数据库连接失败")

        # 查询卡密
        logger.info(f"[Validate] 查询卡密: {card_key}")
        response = client.table('card_keys_table').select('*').eq('key_value', card_key).execute()
        logger.info(f"[Validate] 查询结果: 找到 {len(response.data) if response.data else 0} 条记录")

        if not response.data:
            log_access(client, None, card_key, False, "卡密不存在", device_id)
            return ValidateResponse(can_access=False, msg="卡密不存在")

        card_data = response.data[0]
        card_id = card_data.get('id')
        sales_channel = card_data.get('sales_channel', '')
        logger.info(f"[Validate] 卡密数据: id={card_id}, status={card_data.get('status')}, expire_at={card_data.get('expire_at')}")
        
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
        # - valid（有效）：status=1 且未使用过且销售状态正常
        # - activated（已激活）：status=1 且已使用过且销售状态正常
        # - disabled（已停用）：status=0 或 销售状态为 refunded/disputed
        # 激活状态筛选（需要在应用层处理）
        # - valid（有效）：status=1 且未使用过且销售状态正常
        # - activated（已激活）：status=1 且已使用过且销售状态正常
        # - disabled（已停用）：status=0 或 销售状态为 refunded/disputed
        need_activate_filter = False
        if activate_status:
            if activate_status == 'disabled':
                # 已停用：status=0 或 退款或有纠纷
                # 使用 or 条件：status=0 OR sale_status in ['refunded', 'disputed']
                query = query.or_("status.eq.0,sale_status.in.(refunded,disputed)")
            elif activate_status in ['valid', 'activated']:
                # 有效/已激活：需要在应用层过滤（因为需要处理 NULL 值）
                need_activate_filter = True
                # 先获取 status=1 的所有记录
                query = query.eq('status', 1)
        
        if feishu_url:
            if feishu_url == '__none__':
                # 特殊值：筛选未设置飞书链接的记录（空链接或空字符串）
                query = query.or_('feishu_url.is.null,feishu_url.eq.')
            else:
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
        
        # 过期时间筛选
        if expire_days:
            now = datetime.now()
            if expire_days == 'expired':
                # 已过期：过期时间不为空且小于当前时间
                query = query.not_.is_('expire_at', 'null').lt('expire_at', now.isoformat())
            elif expire_days == 'permanent':
                # 永久有效：过期时间为空
                query = query.is_('expire_at', 'null')
            elif expire_days.startswith('date:'):
                # 按具体日期筛选：date:2026-12-31
                target_date = expire_days[5:]  # 去掉 'date:' 前缀
                # 匹配该日期的过期时间（00:00:00 ~ 23:59:59）
                start_time = f"{target_date}T00:00:00"
                end_time = f"{target_date}T23:59:59"
                query = query.not_.is_('expire_at', 'null').gte('expire_at', start_time).lte('expire_at', end_time)
            else:
                # 未来N天内过期：过期时间在当前时间和N天后之间
                try:
                    days = int(expire_days)
                    future_date = (now + timedelta(days=days)).isoformat()
                    query = query.not_.is_('expire_at', 'null').gte('expire_at', now.isoformat()).lte('expire_at', future_date)
                except ValueError:
                    pass
        
        # 如果需要在应用层过滤设备数量或激活状态，先获取所有数据再过滤
        if need_device_filter or need_activate_filter:
            # 获取所有匹配的数据
            response = query.order('id', desc=True).execute()
            all_data = response.data
            
            # 在应用层过滤
            filtered_data = []
            for card in all_data:
                # 设备数量过滤
                if need_device_filter:
                    try:
                        devices = json.loads(card.get('devices', '[]'))
                        if len(devices) != device_count_filter:
                            continue
                    except:
                        if device_count_filter != 0:
                            continue
                
                # 激活状态过滤（需要处理 NULL 值）
                if need_activate_filter:
                    sale_status = card.get('sale_status')
                    # 排除销售状态为 refunded/disputed 的记录（但允许 NULL）
                    if sale_status in ['refunded', 'disputed']:
                        continue
                    
                    if activate_status == 'valid':
                        # 有效：未使用过（无绑定设备且used_count=0）
                        try:
                            devices = json.loads(card.get('devices', '[]'))
                            if len(devices) > 0 or (card.get('used_count') and card.get('used_count') > 0):
                                continue
                        except:
                            if card.get('used_count') and card.get('used_count') > 0:
                                continue
                    
                    elif activate_status == 'activated':
                        # 已激活：已使用过（有绑定设备或used_count>0）
                        try:
                            devices = json.loads(card.get('devices', '[]'))
                            if len(devices) == 0 and (not card.get('used_count') or card.get('used_count') == 0):
                                continue
                        except:
                            if not card.get('used_count') or card.get('used_count') == 0:
                                continue
                
                filtered_data.append(card)
            
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
                    # 已停用：status=0 或 退款或有纠纷
                    query = query.or_("status.eq.0,sale_status.in.(refunded,disputed)")
                elif activate_status == 'valid':
                    # 有效：status=1 且 未使用过且销售状态正常
                    query = query.eq('status', 1)
                    query = query.eq('devices', '[]').eq('used_count', 0)
                    query = query.not_.in_('sale_status', ['refunded', 'disputed'])
                elif activate_status == 'activated':
                    # 已激活：status=1 且 已使用过且销售状态正常
                    query = query.eq('status', 1)
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
            
            # 过期时间筛选
            expire_days = filters.get('expire_days')
            if expire_days and expire_days != '':
                now = datetime.now()
                if expire_days == 'expired':
                    query = query.not_.is_('expire_at', 'null').lt('expire_at', now.isoformat())
                elif expire_days == 'permanent':
                    query = query.is_('expire_at', 'null')
                elif expire_days.startswith('date:'):
                    # 按具体日期筛选
                    target_date = expire_days[5:]
                    start_time = f"{target_date}T00:00:00"
                    end_time = f"{target_date}T23:59:59"
                    query = query.not_.is_('expire_at', 'null').gte('expire_at', start_time).lte('expire_at', end_time)
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
        safe_log_operation(client, {
            "operator": "admin",
            "operation_type": "batch_update",
            "filter_conditions": request.filters if request.filters else {"ids": request.ids},
            "affected_count": affected_count,
            "affected_ids": affected_ids,
            "update_fields": update_data,
            "remark": request.remark or ""
        })
        
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
                # 已停用：status=0 或 退款或有纠纷
                query = query.or_("status.eq.0,sale_status.in.(refunded,disputed)")
            elif activate_status == 'valid':
                # 有效：status=1 且 未使用过且销售状态正常
                query = query.eq('status', 1)
                query = query.eq('devices', '[]').eq('used_count', 0)
                query = query.not_.in_('sale_status', ['refunded', 'disputed'])
            elif activate_status == 'activated':
                # 已激活：status=1 且 已使用过且销售状态正常
                query = query.eq('status', 1)
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
            if feishu_url == '__none__':
                # 特殊值：筛选未设置飞书链接的记录
                query = query.or_('feishu_url.is.null,feishu_url.eq.')
            else:
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
        
        # 过期时间筛选
        if expire_days and expire_days != '':
            now = datetime.now()
            if expire_days == 'expired':
                query = query.not_.is_('expire_at', 'null').lt('expire_at', now.isoformat())
            elif expire_days == 'permanent':
                query = query.is_('expire_at', 'null')
            elif expire_days.startswith('date:'):
                # 按具体日期筛选
                target_date = expire_days[5:]
                start_time = f"{target_date}T00:00:00"
                end_time = f"{target_date}T23:59:59"
                query = query.not_.is_('expire_at', 'null').gte('expire_at', start_time).lte('expire_at', end_time)
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
            # 使用 operation_time 字段
            if item.get('operation_time'):
                item['created_at'] = item['operation_time'].replace('T', ' ').split('+')[0].split('.')[0]
            elif item.get('created_at'):
                item['created_at'] = item['created_at'].replace('T', ' ').split('+')[0].split('.')[0]
            
            # 解析JSON字段
            if item.get('filter_conditions') and isinstance(item['filter_conditions'], str):
                try:
                    item['filter_conditions'] = json.loads(item['filter_conditions'])
                except:
                    pass
            if item.get('update_fields') and isinstance(item['update_fields'], str):
                try:
                    item['update_fields'] = json.loads(item['update_fields'])
                except:
                    pass
            if item.get('affected_ids') and isinstance(item['affected_ids'], str):
                try:
                    item['affected_ids'] = json.loads(item['affected_ids'])
                except:
                    pass
        
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
    search: Optional[str] = None,
    created_start: Optional[str] = None,
    created_end: Optional[str] = None,
    device_filter: Optional[str] = None,
    expire_days: Optional[str] = None,
    sales_channel: Optional[str] = None,
    exclude_field: Optional[str] = None
):
    """
    获取基于当前筛选条件的各字段可选值
    - 每个字段返回的选项都会排除该字段自身的筛选条件
    - 例如：status 字段的选项会排除 status 筛选条件，但保留其他筛选条件
    - status: 支持 'valid'、'activated'、'disabled' 或数字 '1'、'0'
    """
    try:
        client = get_supabase_client()
        
        # 定义一个辅助函数来构建带筛选条件的查询
        def build_query(exclude: str = None):
            """构建查询，exclude 指定要排除的筛选字段"""
            query = client.table('card_keys_table').select('status, sale_status, feishu_url, link_name, devices, expire_at, sales_channel')
            
            # 应用筛选条件（排除指定字段）
            if status is not None and status != '' and exclude != 'status':
                if status == 'valid':
                    query = query.eq('status', 1).eq('used_count', 0)
                elif status == 'activated':
                    query = query.eq('status', 1).gt('used_count', 0)
                elif status == 'disabled':
                    query = query.or_("status.eq.0,sale_status.in.(refunded,disputed)")
                else:
                    try:
                        query = query.eq('status', int(status))
                    except ValueError:
                        pass
            
            if sale_status and sale_status != '' and exclude != 'sale_status':
                query = query.eq('sale_status', sale_status)
            
            if feishu_url and feishu_url != '' and exclude != 'feishu_url':
                if feishu_url == '__none__':
                    query = query.or_('feishu_url.is.null,feishu_url.eq.')
                else:
                    query = query.eq('feishu_url', feishu_url)
            
            if search and search != '' and exclude != 'search':
                query = query.or_(f"key_value.ilike.%{search}%,user_note.ilike.%{search}%")
            
            if created_start and created_start != '' and exclude != 'created_start':
                query = query.gte('bstudio_create_time', created_start)
            if created_end and created_end != '' and exclude != 'created_end':
                query = query.lte('bstudio_create_time', created_end + 'T23:59:59')
            
            if device_filter and device_filter != '' and exclude != 'device_filter':
                try:
                    device_count = int(device_filter)
                    if device_count == 0:
                        query = query.eq('devices', '[]')
                except ValueError:
                    pass
            
            if expire_days and expire_days != '' and exclude != 'expire_days':
                now = datetime.now()
                if expire_days == 'expired':
                    query = query.not_.is_('expire_at', 'null').lt('expire_at', now.isoformat())
                elif expire_days == 'permanent':
                    query = query.is_('expire_at', 'null')
                elif expire_days.startswith('date:'):
                    target_date = expire_days[5:]
                    start_time = f"{target_date}T00:00:00"
                    end_time = f"{target_date}T23:59:59"
                    query = query.not_.is_('expire_at', 'null').gte('expire_at', start_time).lte('expire_at', end_time)
                else:
                    try:
                        days = int(expire_days)
                        future_date = (now + timedelta(days=days)).isoformat()
                        query = query.not_.is_('expire_at', 'null').gte('expire_at', now.isoformat()).lte('expire_at', future_date)
                    except ValueError:
                        pass
            
            if sales_channel and sales_channel != '' and exclude != 'sales_channel':
                query = query.eq('sales_channel', sales_channel)
            
            return query
        
        # 为每个字段分别执行查询（排除该字段自身的筛选条件）
        
        # 1. 状态统计（排除 status 筛选）
        status_response = build_query(exclude='status').execute()
        status_count = {}
        for item in status_response.data:
            s = item.get('status')
            key = str(s) if s is not None else '0'
            status_count[key] = status_count.get(key, 0) + 1
        
        # 2. 销售状态统计（排除 sale_status 筛选）
        sale_status_response = build_query(exclude='sale_status').execute()
        sale_status_count = {}
        for item in sale_status_response.data:
            s = item.get('sale_status') or ''
            sale_status_count[s] = sale_status_count.get(s, 0) + 1
        
        # 3. 飞书链接统计（排除 feishu_url 筛选）
        feishu_response = build_query(exclude='feishu_url').execute()
        feishu_url_groups = {}
        for item in feishu_response.data:
            url = item.get('feishu_url') or ''
            name = item.get('link_name') or ''
            url_key = url.strip() if url.strip() else ''
            if url_key not in feishu_url_groups:
                feishu_url_groups[url_key] = {"url": url_key, "count": 0, "names": []}
            feishu_url_groups[url_key]["count"] += 1
            if name and name not in feishu_url_groups[url_key]["names"]:
                feishu_url_groups[url_key]["names"].append(name)
        
        feishu_url_list = []
        for url_key, data in feishu_url_groups.items():
            if url_key:
                display_name = data["names"][0] if data["names"] else (url_key[:30] + "..." if len(url_key) > 30 else url_key)
                feishu_url_list.append({"url": url_key, "name": display_name, "count": data["count"]})
            else:
                feishu_url_list.append({"url": "", "name": "未设置", "count": data["count"]})
        feishu_url_list.sort(key=lambda x: x['count'], reverse=True)
        
        # 4. 销售渠道统计（排除 sales_channel 筛选）
        sales_channel_response = build_query(exclude='sales_channel').execute()
        sales_channel_count = {}
        for item in sales_channel_response.data:
            channel = item.get('sales_channel') or '未设置'
            sales_channel_count[channel] = sales_channel_count.get(channel, 0) + 1
        
        sales_channel_list = [{"channel": k, "count": v} for k, v in sales_channel_count.items()]
        sales_channel_list.sort(key=lambda x: x['count'], reverse=True)
        
        # 5. 过期时间统计（排除 expire_days 筛选）
        expire_response = build_query(exclude='expire_days').execute()
        now = datetime.now()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        expired_count = 0
        expire_groups = {}
        permanent_count = 0
        
        for item in expire_response.data:
            expire_at = item.get('expire_at')
            if expire_at is None:
                permanent_count += 1
            else:
                try:
                    if isinstance(expire_at, str):
                        expire_date = datetime.fromisoformat(expire_at.replace('Z', '+00:00')).replace(tzinfo=None)
                    else:
                        expire_date = expire_at
                    expire_date_only = expire_date.replace(hour=0, minute=0, second=0, microsecond=0)
                    date_key = expire_date_only.strftime('%Y-%m-%d')
                    
                    if expire_date_only < today:
                        expired_count += 1
                    else:
                        if date_key not in expire_groups:
                            expire_groups[date_key] = {'date': date_key, 'count': 0}
                        expire_groups[date_key]['count'] += 1
                except Exception:
                    pass
        
        # 构建过期时间分组列表
        expire_groups_list = []
        if expired_count > 0:
            expire_groups_list.append({"value": "expired", "label": "已过期", "count": expired_count})
        for group in sorted(expire_groups.values(), key=lambda x: x['date']):
            expire_groups_list.append({"value": f"date:{group['date']}", "label": f"{group['date']} 到期", "count": group['count']})
        if permanent_count > 0:
            expire_groups_list.append({"value": "permanent", "label": "永久有效", "count": permanent_count})
        
        return {
            "success": True,
            "data": {
                "status": status_count,
                "sale_status": sale_status_count,
                "feishu_url_list": feishu_url_list,
                "sales_channel_list": sales_channel_list,
                "expire_groups_list": expire_groups_list,
                "total": len(status_response.data)
            }
        }
        
    except Exception as e:
        logger.error(f"获取筛选选项失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.get("/api/admin/cards/stats")
async def get_card_stats():
    """
    获取卡密统计数据
    
    返回：
    - total: 总卡密数
    - sold: 已售出数量
    - activated: 已激活数量
    - disabled: 已停用数量
    """
    try:
        client = get_supabase_client()
        
        # 获取总数
        total_response = client.table('card_keys_table').select('id', count='exact').execute()
        total = total_response.count or 0
        
        # 已售出：销售状态为 sold
        sold_response = client.table('card_keys_table').select('id', count='exact').eq('sale_status', 'sold').execute()
        sold = sold_response.count or 0
        
        # 已停用：status=0 或 销售状态为退款/纠纷
        # 使用 RPC 或分开查询
        status_zero_response = client.table('card_keys_table').select('id', count='exact').eq('status', 0).execute()
        refunded_response = client.table('card_keys_table').select('id', count='exact').eq('sale_status', 'refunded').execute()
        disputed_response = client.table('card_keys_table').select('id', count='exact').eq('sale_status', 'disputed').execute()
        
        # 注意：status=0 和 sale_status in (refunded, disputed) 可能有重叠，需要去重
        # 这里简单相加可能会有误差，但为了性能暂时这样处理
        # 更准确的方法是使用数据库层面的 or 查询
        disabled_from_status = status_zero_response.count or 0
        
        # 对于退款和纠纷，需要排除已经是 status=0 的（避免重复计算）
        # 但由于上述已经分开查询，这里先简单处理
        disabled = disabled_from_status
        
        # 获取退款和纠纷中 status=1 的数量（这些也是"已停用"）
        # 这需要在应用层处理或使用更复杂的查询
        # 简化处理：退款和纠纷也算停用
        refunded_count = refunded_response.count or 0
        disputed_count = disputed_response.count or 0
        
        # 获取退款/纠纷中 status=1 的记录（这些是有效但销售状态异常的）
        # 使用 or 查询
        try:
            # 获取所有 status=1 且 sale_status in (refunded, disputed) 的记录
            abnormal_response = client.table('card_keys_table').select('id', count='exact').eq('status', 1).in_('sale_status', ['refunded', 'disputed']).execute()
            disabled += abnormal_response.count or 0
        except:
            # 如果查询失败，使用简化计算
            disabled = disabled_from_status + refunded_count + disputed_count
        
        # 已激活：status=1 且有设备绑定或已使用过
        # 由于需要检查 devices 和 used_count，这需要在应用层处理
        # 先获取所有 status=1 的记录
        activated = 0
        try:
            # 获取 status=1 的记录
            valid_response = client.table('card_keys_table').select('devices, used_count, sale_status').eq('status', 1).execute()
            for card in (valid_response.data or []):
                # 排除销售状态为退款/纠纷的
                if card.get('sale_status') in ['refunded', 'disputed']:
                    continue
                # 检查是否已激活（有设备绑定或已使用过）
                try:
                    devices = json.loads(card.get('devices', '[]'))
                    if len(devices) > 0 or (card.get('used_count') and card.get('used_count') > 0):
                        activated += 1
                except:
                    if card.get('used_count') and card.get('used_count') > 0:
                        activated += 1
        except Exception as e:
            logger.warning(f"计算已激活数量失败: {str(e)}")
        
        return {
            "success": True,
            "data": {
                "total": total,
                "sold": sold,
                "activated": activated,
                "disabled": disabled
            }
        }
        
    except Exception as e:
        logger.error(f"获取统计数据失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.get("/api/admin/cards/feishu-urls")
async def get_feishu_urls():
    """
    获取所有不同的飞书链接列表（用于筛选下拉）
    
    分组逻辑：
    - 按飞书链接（feishu_url）分组
    - 空链接统一合并为"未设置"
    - 显示名称优先取第一个非空名称
    
    返回格式：
    - url: 飞书链接（空链接返回特殊标记"__none__"用于筛选）
    - name: 显示名称（有链接时显示名称或截断链接，无链接显示"未设置"）
    - count: 该链接下的卡密数量
    """
    try:
        client = get_supabase_client()
        
        # 获取所有记录的飞书链接和链接名称
        response = client.table('card_keys_table').select('feishu_url,link_name').execute()
        
        # 按飞书链接分组统计
        url_groups = {}  # key: feishu_url, value: {count, names: []}
        
        for item in response.data:
            url = item.get('feishu_url') or ''
            name = item.get('link_name') or ''
            
            # 空链接统一用空字符串作为 key
            url_key = url.strip() if url.strip() else ''
            
            if url_key not in url_groups:
                url_groups[url_key] = {"url": url_key, "count": 0, "names": []}
            url_groups[url_key]["count"] += 1
            # 收集所有名称（用于显示）
            if name and name not in url_groups[url_key]["names"]:
                url_groups[url_key]["names"].append(name)
        
        # 构建返回结果
        result_list = []
        for url_key, data in url_groups.items():
            if url_key:  # 有链接
                # 优先使用第一个非空名称，否则使用截断的链接
                display_name = data["names"][0] if data["names"] else (url_key[:25] + '...' if len(url_key) > 25 else url_key)
                result_list.append({
                    "url": url_key,
                    "name": display_name,
                    "count": data["count"]
                })
            else:  # 无链接
                result_list.append({
                    "url": "__none__",  # 特殊标记，用于筛选"未设置"
                    "name": "未设置",
                    "count": data["count"]
                })
        
        # 按数量降序排序
        result_list.sort(key=lambda x: x['count'], reverse=True)
        
        return {"success": True, "data": result_list}
        
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


@app.get("/api/admin/expire-groups")
async def get_expire_groups():
    """
    获取过期时间分组统计（用于筛选下拉）
    - 按过期日期分组统计
    - 永久有效单独分组
    返回：日期、数量、是否已过期
    """
    try:
        client = get_supabase_client()
        
        # 获取所有记录的过期时间
        response = client.table('card_keys_table').select('expire_at').execute()
        
        # 使用日期比较（不含时分秒）
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        # 统计每个过期日期的数量
        permanent_count = 0  # 永久有效（expire_at为None）
        expired_count = 0    # 已过期（过期日期小于今天）
        expire_groups = {}   # 未过期的具体日期（过期日期>=今天）
        
        for item in response.data:
            expire_at = item.get('expire_at')
            
            if expire_at is None:
                # 永久有效：创建卡密时没有填写过期时间
                permanent_count += 1
            else:
                # 解析过期时间
                try:
                    if isinstance(expire_at, str):
                        expire_date = datetime.fromisoformat(expire_at.replace('Z', '+00:00')).replace(tzinfo=None)
                    else:
                        expire_date = expire_at
                    
                    # 只保留日期部分（去掉时分秒），统一用日期比较
                    expire_date_only = expire_date.replace(hour=0, minute=0, second=0, microsecond=0)
                    date_key = expire_date_only.strftime('%Y-%m-%d')
                    
                    if expire_date_only < today:
                        # 已过期：过期日期小于今天
                        expired_count += 1
                    else:
                        # 未过期，按日期分组
                        if date_key not in expire_groups:
                            expire_groups[date_key] = {
                                'date': date_key,
                                'count': 0,
                                'is_expired': False
                            }
                        expire_groups[date_key]['count'] += 1
                        
                except Exception as e:
                    logger.warning(f"解析过期时间失败: {expire_at}, {str(e)}")
                    continue
        
        # 转换为列表并按日期排序
        groups = list(expire_groups.values())
        groups.sort(key=lambda x: x['date'])
        
        # 构建返回结果
        result = []
        
        # 1. 已过期（始终显示）
        result.append({
            'type': 'expired',
            'label': '已过期',
            'count': expired_count,
            'is_expired': True
        })
        
        # 2. 未过期的具体日期（按日期排序）
        for group in groups:
            expire_date = datetime.strptime(group['date'], '%Y-%m-%d')
            # 计算距离过期的天数（用日期比较）
            days_remaining = (expire_date - today).days
            label = f"{group['date']} ({days_remaining}天后到期)"
            
            result.append({
                'type': 'date',
                'date': group['date'],
                'label': label,
                'count': group['count'],
                'days_remaining': days_remaining,
                'is_expired': False
            })
        
        # 3. 永久有效（始终显示）
        result.append({
            'type': 'permanent',
            'label': '永久有效',
            'count': permanent_count,
            'is_expired': False
        })
        
        return {"success": True, "data": result}
        
        # 3. 永久有效（始终显示）
        result.append({
            'type': 'permanent',
            'label': '永久有效',
            'count': permanent_count,
            'is_expired': False
        })
        
        return {"success": True, "data": result}
        
    except Exception as e:
        logger.error(f"获取过期时间分组失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.get("/api/admin/cards/export")
async def export_cards(
    ids: Optional[str] = None,
    status: Optional[int] = None,
    format: str = "csv",
    fields: Optional[str] = None
):
    """
    导出卡密
    - ids: 逗号分隔的ID列表，不传则导出全部
    - format: csv, txt 或 xlsx
    - fields: 逗号分隔的字段列表，如 "key_value,feishu_password,status"
    """
    try:
        client = get_supabase_client()
        
        # 定义所有可导出的字段及其显示名称（按列表字段顺序排列）
        field_config = {
            'key_value': {'db_field': 'key_value', 'label': '卡密值'},
            'status': {'db_field': 'status', 'label': '激活状态'},
            'devices': {'db_field': 'devices', 'label': '绑定设备'},
            'expire_at': {'db_field': 'expire_at', 'label': '过期时间'},
            'user_note': {'db_field': 'user_note', 'label': '备注'},
            'link_name': {'db_field': 'link_name', 'label': '链接名称'},
            'bstudio_create_time': {'db_field': 'bstudio_create_time', 'label': '创建时间'},
            'sale_status': {'db_field': 'sale_status', 'label': '销售状态'},
            'sales_channel': {'db_field': 'sales_channel', 'label': '销售渠道'},
            'order_id': {'db_field': 'order_id', 'label': '订单号'},
            'feishu_password': {'db_field': 'feishu_password', 'label': '访问密码'},
            'feishu_url': {'db_field': 'feishu_url', 'label': '飞书链接'},
            'max_devices': {'db_field': 'max_devices', 'label': '最大设备数'},
            'last_used_at': {'db_field': 'last_used_at', 'label': '最后使用时间'}
        }
        
        # 解析要导出的字段
        if fields:
            selected_fields = [f.strip() for f in fields.split(',') if f.strip() in field_config]
        else:
            # 默认只导出卡密值和密码（兼容旧版）
            selected_fields = ['key_value', 'feishu_password']
        
        if not selected_fields:
            return {"success": False, "msg": "请选择至少一个导出字段"}
        
        # 构建 SQL 查询字段列表
        db_fields = [field_config[f]['db_field'] for f in selected_fields]
        query = client.table('card_keys_table').select(','.join(db_fields))
        
        if ids:
            id_list = [int(x) for x in ids.split(',')]
            query = query.in_('id', id_list)
        elif status is not None:
            query = query.eq('status', status)
        
        response = query.order('id', desc=True).execute()
        
        if not response.data:
            return {"success": False, "msg": "没有可导出的数据"}
        
        # 状态映射
        status_map = {1: '有效', 0: '无效'}
        sale_status_map = {
            'unsold': '未售出', 
            'sold': '已售出', 
            'refunded': '已退款', 
            'disputed': '有纠纷',
            'used': '已核销'
        }
        
        # 格式化数据
        def format_value(field, value):
            if value is None:
                return ''
            if field == 'status':
                return status_map.get(value, str(value))
            if field == 'sale_status':
                return sale_status_map.get(value, str(value))
            if field == 'devices':
                # 解析 JSON 数组，显示设备数量
                try:
                    import json
                    devices = json.loads(value) if value else []
                    return f"{len(devices)}台" if devices else '无'
                except:
                    return value
            if field in ['expire_at', 'bstudio_create_time', 'last_used_at']:
                # 格式化时间
                if isinstance(value, str):
                    return value.replace('T', ' ').split('.')[0][:19]
                return str(value)
            return str(value)
        
        # 生成文件名（使用英文避免编码问题）
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"cards_export_{timestamp}"
        
        if format == 'xlsx':
            # Excel格式 - 使用HTML表格格式（Excel兼容）
            headers = [field_config[f]['label'] for f in selected_fields]
            rows = []
            for card in response.data:
                row = [format_value(f, card.get(field_config[f]['db_field'])) for f in selected_fields]
                rows.append(row)
            
            # 生成HTML表格
            html = '<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:x="urn:schemas-microsoft-com:office:excel">'
            html += '<head><meta charset="UTF-8"></head><body>'
            html += '<table border="1" style="border-collapse: collapse;">'
            
            # 表头
            html += '<tr style="background-color: #D4A574; color: white; font-weight: bold;">'
            for h in headers:
                html += f'<th style="padding: 8px;">{h}</th>'
            html += '</tr>'
            
            # 数据行
            for row in rows:
                html += '<tr>'
                for cell in row:
                    html += f'<td style="padding: 6px;">{cell}</td>'
                html += '</tr>'
            
            html += '</table></body></html>'
            
            return StreamingResponse(
                iter([html.encode('utf-8')]),
                media_type="application/vnd.ms-excel",
                headers={"Content-Disposition": f"attachment; filename={filename}.xls"}
            )
        
        # 生成输出
        output = io.StringIO()
        
        if format == 'txt':
            # TXT 格式：每行一个卡密，格式为 "字段1:值1 字段2:值2 ..."
            for card in response.data:
                parts = []
                for field in selected_fields:
                    label = field_config[field]['label']
                    value = format_value(field, card.get(field_config[field]['db_field']))
                    parts.append(f"{label}:{value}")
                output.write(' | '.join(parts) + '\n')
        else:
            # CSV 格式：带表头
            writer = csv.writer(output)
            
            # 写入表头
            headers = [field_config[f]['label'] for f in selected_fields]
            writer.writerow(headers)
            
            # 写入数据行
            for card in response.data:
                row = [format_value(f, card.get(field_config[f]['db_field'])) for f in selected_fields]
                writer.writerow(row)
        
        output.seek(0)
        
        # 确定文件扩展名
        ext = 'txt' if format == 'txt' else 'csv'
        media_type = 'text/plain' if format == 'txt' else 'text/csv; charset=utf-8'
        
        # 返回文件流（CSV 添加 BOM 头以支持 Excel）
        content = output.getvalue()
        if format == 'csv':
            bom = b'\xef\xbb\xbf'
            content = bom + content.encode('utf-8')
        else:
            content = content.encode('utf-8')
        
        return StreamingResponse(
            iter([content]),
            media_type=media_type,
            headers={
                "Content-Disposition": f"attachment; filename={filename}.{ext}"
            }
        )
        
    except Exception as e:
        import traceback
        logger.error(f"导出卡密失败: {str(e)}")
        logger.error(f"堆栈跟踪: {traceback.format_exc()}")
        return {"success": False, "msg": f"导出失败: {str(e)}"}


@app.get("/api/admin/logs/export")
async def export_logs(
    format: str = "csv",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    key_value: Optional[str] = None,
    success: Optional[str] = None
):
    """
    导出访问日志
    - format: csv, txt 或 xlsx
    - start_date: 开始日期 (YYYY-MM-DD)
    - end_date: 结束日期 (YYYY-MM-DD)
    - key_value: 卡密值筛选
    - success: 是否成功 (true/false)
    """
    try:
        client = get_supabase_client()
        
        # 构建查询
        query = client.table('access_logs').select('*')
        
        # 日期筛选
        if start_date:
            query = query.gte('access_time', f'{start_date}T00:00:00')
        if end_date:
            query = query.lte('access_time', f'{end_date}T23:59:59')
        
        # 卡密筛选
        if key_value:
            query = query.eq('key_value', key_value)
        
        # 成功状态筛选
        if success is not None:
            query = query.eq('success', success.lower() == 'true')
        
        # 按时间倒序，限制最多10000条
        response = query.order('access_time', desc=True).limit(10000).execute()
        
        if not response.data:
            return {"success": False, "msg": "没有可导出的日志数据"}
        
        # 格式化数据
        def format_time(value):
            if not value:
                return ''
            if isinstance(value, str):
                return value.replace('T', ' ').split('.')[0][:19]
            return str(value)
        
        # 生成文件名
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"access_logs_{timestamp}"
        
        if format == 'xlsx':
            # Excel格式
            html = '<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:x="urn:schemas-microsoft-com:office:excel">'
            html += '<head><meta charset="UTF-8"></head><body>'
            html += '<table border="1" style="border-collapse: collapse;">'
            
            # 表头
            headers = ['ID', '卡密值', '验证结果', '错误信息', '访问时间']
            html += '<tr style="background-color: #D4A574; color: white; font-weight: bold;">'
            for h in headers:
                html += f'<th style="padding: 8px;">{h}</th>'
            html += '</tr>'
            
            # 数据行
            for log in response.data:
                html += '<tr>'
                html += f'<td style="padding: 6px;">{log.get("id", "")}</td>'
                html += f'<td style="padding: 6px;">{log.get("key_value", "")}</td>'
                result = '成功' if log.get('success') else '失败'
                color = '#10B981' if log.get('success') else '#EF4444'
                html += f'<td style="padding: 6px; color: {color};">{result}</td>'
                html += f'<td style="padding: 6px;">{log.get("error_msg", "") or ""}</td>'
                html += f'<td style="padding: 6px;">{format_time(log.get("access_time"))}</td>'
                html += '</tr>'
            
            html += '</table></body></html>'
            
            return StreamingResponse(
                iter([html.encode('utf-8')]),
                media_type="application/vnd.ms-excel",
                headers={"Content-Disposition": f"attachment; filename={filename}.xls"}
            )
        
        # CSV/TXT格式
        output = io.StringIO()
        
        if format == 'txt':
            for log in response.data:
                result = '成功' if log.get('success') else '失败'
                line = f"ID:{log.get('id', '')} | 卡密:{log.get('key_value', '')} | 结果:{result} | 时间:{format_time(log.get('access_time'))}"
                if log.get('error_msg'):
                    line += f" | 错误:{log.get('error_msg')}"
                output.write(line + '\n')
        else:
            writer = csv.writer(output)
            writer.writerow(['ID', '卡密值', '验证结果', '错误信息', '访问时间'])
            
            for log in response.data:
                result = '成功' if log.get('success') else '失败'
                writer.writerow([
                    log.get('id', ''),
                    log.get('key_value', ''),
                    result,
                    log.get('error_msg', '') or '',
                    format_time(log.get('access_time'))
                ])
        
        output.seek(0)
        
        ext = 'txt' if format == 'txt' else 'csv'
        media_type = 'text/plain' if format == 'txt' else 'text/csv; charset=utf-8'
        
        content = output.getvalue()
        if format == 'csv':
            bom = b'\xef\xbb\xbf'
            content = bom + content.encode('utf-8')
        else:
            content = content.encode('utf-8')
        
        return StreamingResponse(
            iter([content]),
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}.{ext}"}
        )
        
    except Exception as e:
        logger.error(f"导出访问日志失败: {str(e)}")
        return {"success": False, "msg": str(e)}
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


@app.get("/api/admin/cards/import-template")
async def download_cards_import_template():
    """
    下载卡密信息导入模板
    包含所有可导入字段的说明和示例
    字段顺序与列表字段顺序一致
    """
    try:
        output = io.StringIO()
        writer = csv.writer(output)
        
        # 模板表头（与列表字段顺序一致）
        headers = [
            '卡密值', '激活状态', '过期时间', '备注', '链接名称',
            '销售状态', '销售渠道', '订单号', 
            '访问密码', '飞书链接', '最大设备数'
        ]
        writer.writerow(headers)
        
        # 示例数据行1
        writer.writerow([
            'CSS-XXXX-XXXX-XXXX',  # 卡密值（必填）
            '有效',  # 激活状态：有效/无效
            '2026-12-31 23:59:59',  # 过期时间
            '测试备注',  # 备注
            '春招信息表',  # 链接名称
            '未售出',  # 销售状态：未售出/已售出/已核销/已退款/有纠纷
            '小红书',  # 销售渠道
            'ORDER123456',  # 订单号
            'pwd123',  # 访问密码
            'https://my.feishu.cn/base/xxx',  # 飞书链接
            '5'  # 最大设备数
        ])
        
        # 示例数据行2
        writer.writerow([
            'CSS-YYYY-YYYY-YYYY',
            '有效',
            '',
            '',
            '秋招信息表',
            '已售出',
            '淘宝',
            'ORDER789012',
            '',
            'https://my.feishu.cn/base/yyy',
            '5'
        ])
        
        output.seek(0)
        bom = b'\xef\xbb\xbf'
        content = bom + output.getvalue().encode('utf-8')
        
        return StreamingResponse(
            iter([content]),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": "attachment; filename=cards_import_template.csv"
            }
        )
        
    except Exception as e:
        logger.error(f"下载卡密导入模板失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.post("/api/admin/cards/import")
async def import_cards(file: UploadFile = File(...)):
    """
    批量导入卡密信息（智能匹配）
    
    功能：
    - 按卡密值匹配，已存在则更新，不存在则新增
    - 支持所有卡密字段的导入
    - 空值字段不更新（保留原值）
    
    CSV字段说明：
    - 卡密值（必填）：用于匹配的唯一标识
    - 飞书链接：卡密对应的飞书链接
    - 访问密码：飞书访问密码
    - 链接名称：链接的中文名称
    - 激活状态：有效/无效
    - 销售状态：未售出/已售出/已核销/已退款/有纠纷
    - 订单号：销售订单号
    - 销售渠道：如小红书、淘宝等
    - 过期时间：格式 YYYY-MM-DD HH:MM:SS
    - 最大设备数：数字，默认5
    - 备注：用户备注信息
    """
    try:
        client = get_supabase_client()
        
        # 读取上传的CSV文件
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
        
        # 字段映射（中文列名 -> 数据库字段）
        field_mapping = {
            '卡密值': 'key_value',
            '飞书链接': 'feishu_url',
            '访问密码': 'feishu_password',
            '链接名称': 'link_name',
            '激活状态': 'status',
            '销售状态': 'sale_status',
            '订单号': 'order_id',
            '销售渠道': 'sales_channel',
            '过期时间': 'expire_at',
            '最大设备数': 'max_devices',
            '备注': 'user_note'
        }
        
        # 状态映射
        status_map = {
            '有效': 1, '无效': 0,
            '1': 1, '0': 0
        }
        
        sale_status_map = {
            '未售出': 'unsold',
            '已售出': 'sold',
            '已销售': 'sold',
            '已核销': 'used',
            '已退款': 'refunded',
            '有纠纷': 'disputed'
        }
        
        # 解析CSV
        reader = csv.DictReader(io.StringIO(text))
        
        # 标准化列名
        if not reader.fieldnames:
            return {"success": False, "msg": "CSV文件为空或格式错误"}
        
        # 创建列名映射（处理空格和大小写）
        column_map = {}
        for fieldname in reader.fieldnames:
            clean_name = fieldname.strip()
            column_map[clean_name] = fieldname
        
        logger.info(f"CSV列名: {reader.fieldnames}")
        
        # 统计
        added_count = 0
        updated_count = 0
        skipped_count = 0
        error_list = []
        
        for row_num, row in enumerate(reader, start=2):  # 从第2行开始（第1行是表头）
            try:
                # 获取卡密值（必填）
                key_value = None
                for col_name in ['卡密值', '卡密', 'key_value', 'Key']:
                    if col_name in column_map and column_map[col_name] in row:
                        key_value = row[column_map[col_name]].strip().upper()
                        break
                
                if not key_value:
                    skipped_count += 1
                    error_list.append(f"第{row_num}行: 卡密值为空，已跳过")
                    continue
                
                # 构建更新数据
                update_data = {}
                
                # 飞书链接
                if '飞书链接' in column_map and column_map['飞书链接'] in row:
                    val = row[column_map['飞书链接']].strip()
                    if val:
                        update_data['feishu_url'] = val
                
                # 访问密码
                if '访问密码' in column_map and column_map['访问密码'] in row:
                    val = row[column_map['访问密码']].strip()
                    if val:
                        update_data['feishu_password'] = val
                
                # 链接名称
                if '链接名称' in column_map and column_map['链接名称'] in row:
                    val = row[column_map['链接名称']].strip()
                    if val:
                        update_data['link_name'] = val
                
                # 激活状态
                if '激活状态' in column_map and column_map['激活状态'] in row:
                    val = row[column_map['激活状态']].strip()
                    if val:
                        if val in status_map:
                            update_data['status'] = status_map[val]
                        else:
                            error_list.append(f"第{row_num}行: 激活状态'{val}'无效，已跳过该字段")
                
                # 销售状态
                if '销售状态' in column_map and column_map['销售状态'] in row:
                    val = row[column_map['销售状态']].strip()
                    if val:
                        if val in sale_status_map:
                            update_data['sale_status'] = sale_status_map[val]
                            # 已退款/有纠纷自动停用
                            if sale_status_map[val] in ['refunded', 'disputed']:
                                update_data['status'] = 0
                            # 已售出记录时间
                            if sale_status_map[val] == 'sold':
                                update_data['sold_at'] = datetime.now().isoformat()
                        else:
                            error_list.append(f"第{row_num}行: 销售状态'{val}'无效，已跳过该字段")
                
                # 订单号
                if '订单号' in column_map and column_map['订单号'] in row:
                    val = row[column_map['订单号']].strip()
                    if val:
                        update_data['order_id'] = val
                
                # 销售渠道
                if '销售渠道' in column_map and column_map['销售渠道'] in row:
                    val = row[column_map['销售渠道']].strip()
                    if val:
                        update_data['sales_channel'] = val
                
                # 过期时间
                if '过期时间' in column_map and column_map['过期时间'] in row:
                    val = row[column_map['过期时间']].strip()
                    if val:
                        try:
                            # 支持多种时间格式
                            for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%Y/%m/%d']:
                                try:
                                    dt = datetime.strptime(val, fmt)
                                    update_data['expire_at'] = dt.isoformat()
                                    break
                                except ValueError:
                                    continue
                            if 'expire_at' not in update_data:
                                error_list.append(f"第{row_num}行: 过期时间格式错误'{val}'，已跳过该字段")
                        except Exception as e:
                            error_list.append(f"第{row_num}行: 过期时间解析失败: {str(e)}")
                
                # 最大设备数
                if '最大设备数' in column_map and column_map['最大设备数'] in row:
                    val = row[column_map['最大设备数']].strip()
                    if val:
                        try:
                            update_data['max_devices'] = int(val)
                        except ValueError:
                            error_list.append(f"第{row_num}行: 最大设备数'{val}'不是有效数字，已跳过该字段")
                
                # 备注
                if '备注' in column_map and column_map['备注'] in row:
                    val = row[column_map['备注']].strip()
                    if val:
                        update_data['user_note'] = val
                
                # 检查卡密是否存在
                existing = client.table('card_keys_table').select('id').eq('key_value', key_value).execute()
                
                if existing.data:
                    # 更新现有卡密
                    if update_data:
                        client.table('card_keys_table').update(update_data).eq('key_value', key_value).execute()
                        updated_count += 1
                        logger.info(f"更新卡密: {key_value}, 字段: {list(update_data.keys())}")
                    else:
                        skipped_count += 1
                else:
                    # 新增卡密
                    new_card = {
                        'key_value': key_value,
                        'status': update_data.get('status', 1),
                        'feishu_url': update_data.get('feishu_url', ''),
                        'feishu_password': update_data.get('feishu_password', ''),
                        'link_name': update_data.get('link_name', ''),
                        'sale_status': update_data.get('sale_status', 'unsold'),
                        'order_id': update_data.get('order_id'),
                        'sales_channel': update_data.get('sales_channel', ''),
                        'user_note': update_data.get('user_note', ''),
                        'max_devices': update_data.get('max_devices', 5),
                        'sys_platform': '卡密系统',
                        'uuid': str(uuid.uuid4()),
                        'bstudio_create_time': datetime.now().isoformat(),
                        'used_count': 0,
                        'devices': '[]'
                    }
                    
                    # 处理过期时间
                    if 'expire_at' in update_data:
                        new_card['expire_at'] = update_data['expire_at']
                    
                    # 处理已售出时间
                    if 'sold_at' in update_data:
                        new_card['sold_at'] = update_data['sold_at']
                    
                    client.table('card_keys_table').insert(new_card).execute()
                    added_count += 1
                    logger.info(f"新增卡密: {key_value}")
                    
            except Exception as e:
                error_list.append(f"第{row_num}行处理失败: {str(e)}")
                logger.error(f"第{row_num}行处理失败: {str(e)}")
        
        # 记录操作日志
        if added_count > 0 or updated_count > 0:
            safe_log_operation(client, {
                "operator": "admin",
                "operation_type": "import_cards",
                "filter_conditions": {"filename": file.filename},
                "affected_count": added_count + updated_count,
                "affected_ids": [],
                "update_fields": {"added": added_count, "updated": updated_count},
                "remark": f"导入卡密: 新增{added_count}条, 更新{updated_count}条"
            })
        
        result_msg = f"导入完成：新增 {added_count} 条，更新 {updated_count} 条"
        if skipped_count > 0:
            result_msg += f"，跳过 {skipped_count} 条"
        
        return {
            "success": True,
            "msg": result_msg,
            "added": added_count,
            "updated": updated_count,
            "skipped": skipped_count,
            "errors": error_list[:20]  # 只返回前20条错误
        }
        
    except Exception as e:
        logger.error(f"导入卡密失败: {str(e)}")
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
        generated_count = len(response.data)
        generated_ids = [card['id'] for card in response.data]
        
        # 记录操作日志
        safe_log_operation(client, {
            "operator": "admin",
            "operation_type": "batch_generate",
            "filter_conditions": {
                "count": req.count,
                "prefix": req.prefix,
                "link_name": req.link_name,
                "feishu_url": req.feishu_url,
                "expire_at": expire_at,
                "sales_channel": req.sales_channel
            },
            "affected_count": generated_count,
            "affected_ids": generated_ids,
            "update_fields": {},
            "remark": f"批量生成 {generated_count} 条卡密"
        })
        
        return {
            "success": True,
            "data": response.data,
            "msg": f"成功生成 {generated_count} 个卡密"
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
        
        # 记录操作日志（仅在有更新内容时，失败不影响主操作）
        if update_data:
            updated_card = response.data[0]
            safe_log_operation(client, {
                "operator": "admin",
                "operation_type": "single_update",
                "filter_conditions": {"card_id": card_id, "key_value": updated_card.get('key_value', '')},
                "affected_count": 1,
                "affected_ids": [card_id],
                "update_fields": update_data,
                "remark": f"编辑卡密: {updated_card.get('key_value', '')}"
            })
        
        return {"success": True, "data": response.data[0], "msg": "更新成功"}
        
    except Exception as e:
        logger.error(f"更新卡密失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.delete("/api/admin/cards/{card_id}")
async def delete_card_key(card_id: int):
    """删除卡密"""
    try:
        client = get_supabase_client()
        
        # 先获取卡密信息用于日志记录
        card_info = client.table('card_keys_table').select('key_value').eq('id', card_id).execute()
        deleted_key = card_info.data[0]['key_value'] if card_info.data else 'unknown'
        
        # 先删除相关的访问日志记录
        client.table('access_logs').delete().eq('card_key_id', card_id).execute()
        
        # 再删除卡密
        response = client.table('card_keys_table').delete().eq('id', card_id).execute()
        
        if not response.data:
            return {"success": False, "msg": "卡密不存在"}
        
        # 记录操作日志
        safe_log_operation(client, {
            "operator": "admin",
            "operation_type": "single_delete",
            "filter_conditions": {"card_id": card_id, "key_value": deleted_key},
            "affected_count": 1,
            "affected_ids": [card_id],
            "update_fields": {},
            "remark": f"删除卡密: {deleted_key}"
        })
        
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
        
        # 操作类型映射
        operation_type_map = {
            "delete": "batch_delete",
            "activate": "batch_activate",
            "deactivate": "batch_deactivate",
            "update_url": "batch_update_url"
        }
        
        if operation.action == "delete":
            # 先删除相关的访问日志记录
            client.table('access_logs').delete().in_('card_key_id', operation.ids).execute()
            # 再删除卡密
            response = client.table('card_keys_table').delete().in_('id', operation.ids).execute()
            # Supabase 可能不返回被删除的数据，使用请求数量作为实际影响数
            affected_count = len(response.data) if response.data else len(operation.ids)
            
            # 记录操作日志
            safe_log_operation(client, {
                "operator": "admin",
                "operation_type": operation_type_map["delete"],
                "filter_conditions": {"ids": operation.ids},
                "affected_count": affected_count,
                "affected_ids": operation.ids,
                "update_fields": {},
                "remark": f"批量删除 {affected_count} 条卡密"
            })
            
            return {"success": True, "msg": f"成功删除 {affected_count} 条记录"}
            
        elif operation.action == "activate":
            response = client.table('card_keys_table').update({"status": 1}).in_('id', operation.ids).execute()
            # Supabase 可能不返回更新的数据，使用请求数量作为实际影响数
            affected_count = len(response.data) if response.data else len(operation.ids)
            
            # 记录操作日志
            safe_log_operation(client, {
                "operator": "admin",
                "operation_type": operation_type_map["activate"],
                "filter_conditions": {"ids": operation.ids},
                "affected_count": affected_count,
                "affected_ids": operation.ids,
                "update_fields": {"status": 1},
                "remark": f"批量激活 {affected_count} 条卡密"
            })
            
            return {"success": True, "msg": f"成功激活 {affected_count} 条记录"}
            
        elif operation.action == "deactivate":
            response = client.table('card_keys_table').update({"status": 0}).in_('id', operation.ids).execute()
            # Supabase 可能不返回更新的数据，使用请求数量作为实际影响数
            affected_count = len(response.data) if response.data else len(operation.ids)
            
            # 记录操作日志
            safe_log_operation(client, {
                "operator": "admin",
                "operation_type": operation_type_map["deactivate"],
                "filter_conditions": {"ids": operation.ids},
                "affected_count": affected_count,
                "affected_ids": operation.ids,
                "update_fields": {"status": 0},
                "remark": f"批量停用 {affected_count} 条卡密"
            })
            
            return {"success": True, "msg": f"成功停用 {affected_count} 条记录"}
            
        elif operation.action == "update_url":
            if not operation.feishu_url:
                return {"success": False, "msg": "请提供飞书链接"}
            response = client.table('card_keys_table').update({
                "feishu_url": operation.feishu_url,
                "feishu_password": operation.feishu_password or ""
            }).in_('id', operation.ids).execute()
            affected_count = len(response.data)
            
            # 记录操作日志
            safe_log_operation(client, {
                "operator": "admin",
                "operation_type": operation_type_map["update_url"],
                "filter_conditions": {"ids": operation.ids},
                "affected_count": affected_count,
                "affected_ids": operation.ids,
                "update_fields": {"feishu_url": operation.feishu_url, "feishu_password": operation.feishu_password or ""},
                "remark": f"批量更新飞书链接 {affected_count} 条"
            })
            
            return {"success": True, "msg": f"成功更新 {affected_count} 条记录"}
        
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
    sale_status: Optional[str] = None,
    days: Optional[int] = None  # 时间范围筛选：最近N天
):
    """获取访问日志，关联卡密详细信息"""
    try:
        client = get_supabase_client()
        
        # 如果有销售状态筛选，先获取符合销售状态的卡密列表
        sale_status_key_values = None
        if sale_status:
            cards_filter = client.table('card_keys_table').select('key_value').eq('sale_status', sale_status).execute()
            sale_status_key_values = [card['key_value'] for card in (cards_filter.data or [])]
            # 如果没有符合条件的卡密，直接返回空结果
            if not sale_status_key_values:
                return {
                    "success": True,
                    "data": [],
                    "total": 0,
                    "page": page,
                    "page_size": page_size
                }
        
        query = client.table('access_logs').select('*', count='exact')
        
        if card_key_id:
            query = query.eq('card_key_id', card_key_id)
        if success is not None:
            query = query.eq('success', success)
        if search:
            query = query.ilike('key_value', f'%{search}%')
        if days and days > 0:
            # 筛选最近N天的日志
            cutoff_time = (datetime.now() - timedelta(days=days)).isoformat()
            query = query.gte('access_time', cutoff_time)
        # 销售状态筛选：使用预先获取的卡密列表
        if sale_status_key_values is not None:
            query = query.in_('key_value', sale_status_key_values)
        
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
                    'key_value,user_note,sale_status,sales_channel,order_id,status,devices,max_devices,expire_at,link_name'
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
                    log['link_name'] = card_info.get('link_name', '')
        
        return {
            "success": True,
            "data": logs or [],
            "total": response.count or 0,
            "page": page,
            "page_size": page_size
        }
        
    except Exception as e:
        logger.error(f"获取访问日志失败: {str(e)}")
        return {"success": False, "msg": str(e)}


class CleanLogsRequest(BaseModel):
    """清理日志请求"""
    condition: str  # all, fail, success, expired
    days: int  # 0表示不限时间


@app.post("/api/admin/logs/preview-clean")
async def preview_clean_logs(request: CleanLogsRequest):
    """预览清理数量"""
    try:
        client = get_supabase_client()
        
        query = client.table('access_logs').select('id, key_value', count='exact')
        
        # 应用条件筛选
        if request.condition == 'fail':
            query = query.eq('success', False)
        elif request.condition == 'success':
            query = query.eq('success', True)
        elif request.condition == 'expired':
            # 查找过期卡密的日志
            now = datetime.now().isoformat()
            expired_cards = client.table('card_keys_table').select('key_value').not_.is_('expire_at', 'null').lt('expire_at', now).execute()
            expired_keys = [card['key_value'] for card in (expired_cards.data or [])]
            if expired_keys:
                query = query.in_('key_value', expired_keys)
            else:
                return {"success": True, "count": 0, "condition": request.condition, "days": request.days}
        
        # 应用时间筛选
        if request.days > 0:
            cutoff_time = (datetime.now() - timedelta(days=request.days)).isoformat()
            query = query.lt('access_time', cutoff_time)
        
        response = query.execute()
        
        return {
            "success": True,
            "count": response.count or 0,
            "condition": request.condition,
            "days": request.days
        }
        
    except Exception as e:
        logger.error(f"预览清理数量失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.post("/api/admin/logs/clean")
async def clean_logs(request: CleanLogsRequest):
    """批量清理访问日志"""
    try:
        client = get_supabase_client()
        
        # 先获取符合条件的日志ID
        query = client.table('access_logs').select('id')
        
        # 应用条件筛选
        if request.condition == 'fail':
            query = query.eq('success', False)
        elif request.condition == 'success':
            query = query.eq('success', True)
        elif request.condition == 'expired':
            # 查找过期卡密的日志
            now = datetime.now().isoformat()
            expired_cards = client.table('card_keys_table').select('key_value').not_.is_('expire_at', 'null').lt('expire_at', now).execute()
            expired_keys = [card['key_value'] for card in (expired_cards.data or [])]
            if expired_keys:
                query = query.in_('key_value', expired_keys)
            else:
                # 没有过期卡密，无需清理
                return {"success": True, "msg": "没有符合条件的日志", "deleted_count": 0}
        
        # 应用时间筛选
        if request.days > 0:
            cutoff_time = (datetime.now() - timedelta(days=request.days)).isoformat()
            query = query.lt('access_time', cutoff_time)
        
        response = query.execute()
        
        if not response.data:
            return {"success": True, "msg": "没有符合条件的日志", "deleted_count": 0}
        
        # 获取要删除的ID列表
        ids_to_delete = [log['id'] for log in response.data]
        deleted_count = len(ids_to_delete)
        
        # 执行删除（分批处理，每批最多1000条）
        batch_size = 1000
        for i in range(0, deleted_count, batch_size):
            batch_ids = ids_to_delete[i:i + batch_size]
            client.table('access_logs').delete().in_('id', batch_ids).execute()
        
        logger.info(f"批量清理访问日志完成: 条件={request.condition}, 天数={request.days}, 删除数量={deleted_count}")
        
        return {
            "success": True,
            "msg": f"成功清理 {deleted_count} 条日志",
            "deleted_count": deleted_count
        }
        
    except Exception as e:
        logger.error(f"清理访问日志失败: {str(e)}")
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


# ==================== 统计报表 API ====================

@app.get("/api/admin/statistics/trend")
async def get_statistics_trend(
    period: str = "day",  # day, week, month
    days: int = 30
):
    """获取卡密使用趋势数据
    
    Args:
        period: 统计周期 - day(按日), week(按周), month(按月)
        days: 统计天数范围
    """
    try:
        client = get_supabase_client()
        
        # 计算日期范围
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        # 获取访问日志
        logs_response = client.table('access_logs').select('*').gte('access_time', start_date.isoformat()).execute()
        logs = logs_response.data or []
        
        # 获取卡密数据
        cards_response = client.table('card_keys_table').select('*').execute()
        cards = cards_response.data or []
        
        # 按周期分组统计
        trend_data = {}
        
        for log in logs:
            access_time = datetime.fromisoformat(log['access_time'].replace('Z', '+00:00'))
            
            if period == "day":
                key = access_time.strftime('%Y-%m-%d')
            elif period == "week":
                # 获取周起始日期
                week_start = access_time - timedelta(days=access_time.weekday())
                key = week_start.strftime('%Y-%m-%d')
            else:  # month
                key = access_time.strftime('%Y-%m')
            
            if key not in trend_data:
                trend_data[key] = {
                    'date': key,
                    'visits': 0,
                    'success': 0,
                    'unique_users': set()
                }
            
            trend_data[key]['visits'] += 1
            if log.get('success'):
                trend_data[key]['success'] += 1
            if log.get('key_value'):
                trend_data[key]['unique_users'].add(log['key_value'])
        
        # 转换为列表并计算唯一用户数
        result = []
        for key in sorted(trend_data.keys()):
            data = trend_data[key]
            result.append({
                'date': data['date'],
                'visits': data['visits'],
                'success': data['success'],
                'unique_users': len(data['unique_users'])
            })
        
        return {
            "success": True,
            "data": result,
            "period": period,
            "total_visits": sum(d['visits'] for d in result),
            "total_success": sum(d['success'] for d in result)
        }
        
    except Exception as e:
        logger.error(f"获取趋势数据失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.get("/api/admin/statistics/distribution")
async def get_statistics_distribution():
    """获取销售状态和设备绑定分布统计"""
    try:
        client = get_supabase_client()
        
        # 获取所有卡密
        response = client.table('card_keys_table').select('*').execute()
        cards = response.data or []
        
        # 销售状态分布
        sales_distribution = {
            'unsold': 0,
            'sold': 0,
            'refunded': 0,
            'disputed': 0
        }
        
        # 激活状态分布
        status_distribution = {
            'valid': 0,
            'activated': 0,
            'disabled': 0,
            'expired': 0
        }
        
        # 设备绑定分布
        device_distribution = {
            '0': 0,
            '1': 0,
            '2': 0,
            '3': 0,
            '4': 0,
            '5': 0
        }
        
        # 过期状态
        now = datetime.now()
        expired_count = 0
        expiring_7days = 0
        expiring_30days = 0
        
        for card in cards:
            # 销售状态
            sales_status = card.get('sales_status', 'unsold') or 'unsold'
            if sales_status in sales_distribution:
                sales_distribution[sales_status] += 1
            
            # 激活状态
            status = card.get('status', 1)
            if status == 1:
                status_distribution['valid'] += 1
            else:
                status_distribution['disabled'] += 1
            
            # 设备绑定
            devices = card.get('devices')
            if devices:
                try:
                    device_list = json.loads(devices) if isinstance(devices, str) else devices
                    device_count = len(device_list)
                except:
                    device_count = 0
            else:
                device_count = 0
            
            device_key = str(min(device_count, 5))
            device_distribution[device_key] += 1
            
            # 过期状态
            expire_at = card.get('expire_at')
            if expire_at:
                try:
                    expire_time = datetime.fromisoformat(expire_at.replace('Z', '+00:00'))
                    if expire_time < now:
                        expired_count += 1
                    elif expire_time < now + timedelta(days=7):
                        expiring_7days += 1
                    elif expire_time < now + timedelta(days=30):
                        expiring_30days += 1
                except:
                    pass
        
        return {
            "success": True,
            "data": {
                "total": len(cards),
                "sales_distribution": sales_distribution,
                "status_distribution": status_distribution,
                "device_distribution": device_distribution,
                "expire_status": {
                    "expired": expired_count,
                    "expiring_7days": expiring_7days,
                    "expiring_30days": expiring_30days,
                    "permanent": len(cards) - expired_count - expiring_7days - expiring_30days
                }
            }
        }
        
    except Exception as e:
        logger.error(f"获取分布统计失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.get("/api/admin/statistics/overview")
async def get_statistics_overview():
    """获取统计概览数据"""
    try:
        client = get_supabase_client()
        
        # 卡密统计
        cards_response = client.table('card_keys_table').select('*', count='exact').execute()
        total_cards = cards_response.count or 0
        cards = cards_response.data or []
        
        # 已售出：销售状态为 sold
        sold_cards = len([c for c in cards if c.get('sale_status') == 'sold'])
        
        # 今日访问量
        today = datetime.now().strftime('%Y-%m-%d')
        today_logs = client.table('access_logs').select('id', count='exact').gte('access_time', f'{today}T00:00:00').execute()
        today_visits = today_logs.count or 0
        
        # 今日成功验证
        today_success = client.table('access_logs').select('id', count='exact').gte('access_time', f'{today}T00:00:00').eq('success', True).execute()
        today_success_count = today_success.count or 0
        
        # 本周新增卡密
        week_start = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime('%Y-%m-%d')
        week_cards = client.table('card_keys_table').select('id', count='exact').gte('bstudio_create_time', f'{week_start}T00:00:00').execute()
        week_new_cards = week_cards.count or 0
        
        # 总访问量
        all_logs = client.table('access_logs').select('id', count='exact').execute()
        total_visits = all_logs.count or 0
        
        return {
            "success": True,
            "data": {
                "total_cards": total_cards,
                "sold_cards": sold_cards,
                "today_visits": today_visits,
                "today_success": today_success_count,
                "week_new_cards": week_new_cards,
                "total_visits": total_visits
            }
        }
        
    except Exception as e:
        logger.error(f"获取统计概览失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.get("/api/admin/statistics/export")
async def export_statistics():
    """导出统计报表数据"""
    try:
        client = get_supabase_client()
        
        # 获取所有数据
        cards_response = client.table('card_keys_table').select('*').execute()
        cards = cards_response.data or []
        
        logs_response = client.table('access_logs').select('*').execute()
        logs = logs_response.data or []
        
        # 汇总统计
        now = datetime.now()
        
        # 卡密统计
        total_cards = len(cards)
        valid_cards = len([c for c in cards if c.get('status') == 1])
        
        # 销售状态统计
        sales_stats = {}
        for card in cards:
            status = card.get('sales_status', 'unsold') or 'unsold'
            sales_stats[status] = sales_stats.get(status, 0) + 1
        
        # 过期统计
        expired = 0
        expiring_7days = 0
        for card in cards:
            expire_at = card.get('expire_at')
            if expire_at:
                try:
                    expire_time = datetime.fromisoformat(expire_at.replace('Z', '+00:00'))
                    if expire_time < now:
                        expired += 1
                    elif expire_time < now + timedelta(days=7):
                        expiring_7days += 1
                except:
                    pass
        
        # 访问统计
        total_visits = len(logs)
        success_visits = len([l for l in logs if l.get('success')])
        
        # 今日统计
        today = now.strftime('%Y-%m-%d')
        today_logs = [l for l in logs if l.get('access_time', '').startswith(today)]
        today_visits = len(today_logs)
        
        # 构建导出数据
        export_data = {
            "export_time": now.isoformat(),
            "summary": {
                "total_cards": total_cards,
                "valid_cards": valid_cards,
                "invalid_cards": total_cards - valid_cards,
                "expired_cards": expired,
                "expiring_7days": expiring_7days,
                "total_visits": total_visits,
                "success_visits": success_visits,
                "today_visits": today_visits,
                "sales_distribution": sales_stats
            },
            "cards": cards,
            "logs": logs
        }
        
        return {
            "success": True,
            "data": export_data
        }
        
    except Exception as e:
        logger.error(f"导出统计报表失败: {str(e)}")
        return {"success": False, "msg": str(e)}


# ==================== 链接健康检测 API ====================

import httpx
import asyncio

@app.get("/api/admin/link-health")
async def get_link_health():
    """获取所有链接健康状态列表"""
    try:
        client = get_supabase_client()
        
        # 尝试查询链接健康表（如果存在）
        try:
            health_response = client.table('link_health_table').select('*').order('last_check_time', desc=True).execute()
            health_data = health_response.data or []
        except Exception:
            # 表不存在，返回空数据
            health_data = []
        
        # 获取所有唯一的飞书链接
        cards_response = client.table('card_keys_table').select('feishu_url, link_name').execute()
        cards = cards_response.data or []
        
        # 统计唯一链接，同时收集每个链接的所有名称（去重）
        unique_links = {}
        link_names = {}  # 收集每个URL的所有名称
        
        for card in cards:
            url = card.get('feishu_url')
            if url:
                # 收集名称
                name = card.get('link_name') or ''
                if url not in link_names:
                    link_names[url] = set()
                if name:  # 只收集非空名称
                    link_names[url].add(name)
                
                # 初始化链接数据
                if url not in unique_links:
                    unique_links[url] = {
                        'url': url,
                        'name': '',
                        'status': 'unknown',
                        'last_check_time': None,
                        'http_code': None,
                        'error_message': None
                    }
        
        # 处理名称：优先使用非空名称，多个名称用逗号分隔
        for url in unique_links:
            names = link_names.get(url, set())
            # 过滤空字符串，去重后排序
            names_list = sorted([n for n in names if n])
            if names_list:
                unique_links[url]['name'] = ', '.join(names_list)
            else:
                unique_links[url]['name'] = ''
        
        # 合并健康状态数据
        for health in health_data:
            url = health.get('feishu_url')
            if url in unique_links:
                unique_links[url].update({
                    'status': health.get('status', 'unknown'),
                    'last_check_time': health.get('last_check_time'),
                    'http_code': health.get('http_code'),
                    'error_message': health.get('error_message'),
                    'consecutive_failures': health.get('consecutive_failures', 0)
                })
        
        # 统计汇总
        links_list = list(unique_links.values())
        summary = {
            'total': len(links_list),
            'healthy': len([l for l in links_list if l['status'] == 'healthy']),
            'unhealthy': len([l for l in links_list if l['status'] == 'unhealthy']),
            'unknown': len([l for l in links_list if l['status'] == 'unknown'])
        }
        
        return {
            "success": True,
            "data": links_list,
            "summary": summary
        }
        
    except Exception as e:
        logger.error(f"获取链接健康状态失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.post("/api/admin/link-health/check")
async def check_all_links():
    """检测所有链接健康状态"""
    try:
        client = get_supabase_client()
        
        # 获取所有唯一的飞书链接，同时收集每个链接的所有名称
        cards_response = client.table('card_keys_table').select('feishu_url, link_name').execute()
        cards = cards_response.data or []
        
        # 收集每个URL的所有名称（去重）
        link_names = {}
        for card in cards:
            url = card.get('feishu_url')
            if url:
                name = card.get('link_name') or ''
                if url not in link_names:
                    link_names[url] = set()
                if name:
                    link_names[url].add(name)
        
        if not link_names:
            return {"success": True, "msg": "没有需要检测的链接", "results": []}
        
        # 批量检测链接
        results = []
        async with httpx.AsyncClient(timeout=10.0) as http_client:
            for url, names in link_names.items():
                # 处理名称：多个名称用逗号分隔
                names_list = sorted([n for n in names if n])
                name = ', '.join(names_list) if names_list else ''
                result = await check_single_link(http_client, url, name, client)
                results.append(result)
        
        # 统计结果
        healthy_count = len([r for r in results if r['status'] == 'healthy'])
        unhealthy_count = len([r for r in results if r['status'] == 'unhealthy'])
        
        return {
            "success": True,
            "msg": f"检测完成: {healthy_count} 个正常, {unhealthy_count} 个异常",
            "results": results,
            "summary": {
                "total": len(results),
                "healthy": healthy_count,
                "unhealthy": unhealthy_count
            }
        }
        
    except Exception as e:
        logger.error(f"检测链接健康状态失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.post("/api/admin/link-health/check-single")
async def check_single_link_api(request: Request):
    """检测单个链接健康状态"""
    try:
        body = await request.json()
        url = body.get('url')
        
        if not url:
            return {"success": False, "msg": "缺少链接URL"}
        
        client = get_supabase_client()
        
        # 获取该URL的所有链接名称（去重）
        cards_response = client.table('card_keys_table').select('link_name').eq('feishu_url', url).execute()
        names = set()
        if cards_response.data:
            for card in cards_response.data:
                name = card.get('link_name') or ''
                if name:
                    names.add(name)
        
        # 处理名称：多个名称用逗号分隔
        names_list = sorted([n for n in names if n])
        name = ', '.join(names_list) if names_list else ''
        
        async with httpx.AsyncClient(timeout=10.0) as http_client:
            result = await check_single_link(http_client, url, name, client)
        
        return {"success": True, "data": result}
        
    except Exception as e:
        logger.error(f"检测单个链接失败: {str(e)}")
        return {"success": False, "msg": str(e)}


async def check_single_link(http_client: httpx.AsyncClient, url: str, name: str, db_client) -> dict:
    """检测单个链接的健康状态"""
    # 使用带时区的时间格式，确保前端正确解析
    from datetime import timezone
    beijing_tz = timezone(timedelta(hours=8))
    now = datetime.now(beijing_tz)
    
    result = {
        'url': url,
        'name': name,
        'status': 'unknown',
        'http_code': None,
        'error_message': None,
        'check_time': now.isoformat()
    }
    
    try:
        # 判断是否是飞书链接
        is_feishu = 'feishu.cn' in url or 'larksuite.com' in url
        
        # 飞书链接使用GET请求（HEAD可能返回404）
        if is_feishu:
            # 使用GET请求，但不下载body
            response = await http_client.get(url, follow_redirects=True)
        else:
            # 其他链接使用HEAD请求
            response = await http_client.head(url, follow_redirects=True)
        
        result['http_code'] = response.status_code
        
        # 检查是否重定向到登录页面
        final_url = str(response.url)
        is_login_redirect = 'login' in final_url.lower() or 'passport' in final_url.lower()
        
        if response.status_code == 200:
            result['status'] = 'healthy'
            if is_login_redirect:
                result['error_message'] = '需要登录访问'
        elif response.status_code in [301, 302, 303, 307, 308]:
            result['status'] = 'healthy'  # 重定向也视为正常
            if is_login_redirect:
                result['error_message'] = '需要登录访问'
            else:
                result['error_message'] = f'重定向到其他地址'
        elif response.status_code in [401, 403]:
            result['status'] = 'healthy'  # 需要认证也视为链接有效
            result['error_message'] = '需要认证访问'
        elif response.status_code == 404:
            # 飞书链接404可能是需要登录，检查URL格式是否正确
            if is_feishu:
                # 飞书链接格式正确就认为有效
                if '/app/' in url or '/base/' in url or '/docx/' in url or '/wiki/' in url:
                    result['status'] = 'healthy'
                    result['error_message'] = '飞书链接（需登录验证）'
                else:
                    result['status'] = 'unhealthy'
                    result['error_message'] = '链接不存在(404)'
            else:
                result['status'] = 'unhealthy'
                result['error_message'] = '链接不存在(404)'
        else:
            result['status'] = 'unhealthy'
            result['error_message'] = f'HTTP状态码: {response.status_code}'
            
    except httpx.TimeoutException:
        result['status'] = 'unhealthy'
        result['error_message'] = '请求超时'
    except httpx.ConnectError:
        result['status'] = 'unhealthy'
        result['error_message'] = '连接失败'
    except Exception as e:
        result['status'] = 'unhealthy'
        result['error_message'] = str(e)[:200]
    
    # 更新数据库
    try:
        # 检查记录是否存在
        existing = db_client.table('link_health_table').select('id').eq('feishu_url', url).execute()
        
        next_check = now + timedelta(hours=24)  # 24小时后再检测
        
        if existing.data and len(existing.data) > 0:
            # 更新现有记录
            record_id = existing.data[0]['id']
            db_client.table('link_health_table').update({
                'status': result['status'],
                'http_code': result['http_code'],
                'error_message': result['error_message'],
                'last_check_time': now.isoformat(),
                'next_check_time': next_check.isoformat(),
                'consecutive_failures': 0 if result['status'] == 'healthy' else 1,
                'total_checks': 1,  # 每次检测重置
                'updated_at': now.isoformat()
            }).eq('id', record_id).execute()
        else:
            # 创建新记录
            db_client.table('link_health_table').insert({
                'feishu_url': url,
                'link_name': name,
                'status': result['status'],
                'http_code': result['http_code'],
                'error_message': result['error_message'],
                'last_check_time': now.isoformat(),
                'next_check_time': next_check.isoformat(),
                'consecutive_failures': 0 if result['status'] == 'healthy' else 1,
                'total_checks': 1,
                'successful_checks': 1 if result['status'] == 'healthy' else 0
            }).execute()
    except Exception as e:
        logger.warning(f"保存链接健康状态失败: {str(e)}")
    
    return result


@app.get("/api/admin/link-health/summary")
async def get_link_health_summary():
    """获取链接健康状态汇总"""
    try:
        client = get_supabase_client()
        
        # 获取所有卡密
        cards_response = client.table('card_keys_table').select('feishu_url').execute()
        cards = cards_response.data or []
        
        total_links = len(set(c.get('feishu_url') for c in cards if c.get('feishu_url')))
        cards_without_link = len([c for c in cards if not c.get('feishu_url')])
        
        # 尝试获取健康状态
        try:
            health_response = client.table('link_health_table').select('status').execute()
            health_data = health_response.data or []
            
            healthy = len([h for h in health_data if h.get('status') == 'healthy'])
            unhealthy = len([h for h in health_data if h.get('status') == 'unhealthy'])
            unknown = len([h for h in health_data if h.get('status') == 'unknown'])
        except Exception:
            healthy = 0
            unhealthy = 0
            unknown = total_links
        
        return {
            "success": True,
            "data": {
                "total_links": total_links,
                "cards_without_link": cards_without_link,
                "healthy": healthy,
                "unhealthy": unhealthy,
                "unknown": unknown,
                "needs_check": total_links - healthy - unhealthy
            }
        }
        
    except Exception as e:
        logger.error(f"获取链接健康汇总失败: {str(e)}")
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


@app.get("/api/debug/db")
async def debug_database():
    """调试 API - 返回数据库连接状态"""
    import os
    from storage.database.db_client import get_db_mode, _load_env
    
    # 加载环境变量
    _load_env()
    
    supabase_url = os.getenv("COZE_SUPABASE_URL", "")
    database_url = os.getenv("DATABASE_URL", "")
    pgdatabase_url = os.getenv("PGDATABASE_URL", "")
    local_dev = os.getenv("LOCAL_DEV_MODE", "")
    
    debug_info = {
        "env_vars": {
            "COZE_SUPABASE_URL": supabase_url[:50] + "..." if supabase_url and len(supabase_url) > 50 else supabase_url,
            "DATABASE_URL": database_url[:50] + "..." if database_url and len(database_url) > 50 else database_url,
            "PGDATABASE_URL": pgdatabase_url[:50] + "..." if pgdatabase_url and len(pgdatabase_url) > 50 else pgdatabase_url,
            "LOCAL_DEV_MODE": local_dev
        },
        "db_mode": get_db_mode(),
        "checks": {}
    }
    
    try:
        client = get_supabase_client()
        debug_info["checks"]["client_type"] = type(client).__name__
        
        # 测试查询
        result = client.table('card_keys_table').select('id', count='exact').limit(1).execute()
        debug_info["checks"]["query_success"] = True
        debug_info["checks"]["total_records"] = result.count
    except Exception as e:
        debug_info["checks"]["query_success"] = False
        debug_info["checks"]["error"] = str(e)
    
    return debug_info


# ==================== 静态文件服务 ====================

# 微信验证文件配置（可配置多个）
WECHAT_VERIFY_FILES = {
    "f6f3f1102e163b12197a863f1873b9b2.txt": "215382aa832da898a1c0ad9e2e48a96a909277a9",
    "fed9e7ab77a3dde24e1102145c87bd3f.txt": "c1c1e2703438fbd0fc7816d7249a9a5385161b66",
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


# ==================== 健康检查 ====================

@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok"}


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
