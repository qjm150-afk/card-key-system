"""
卡密验证系统 - 主入口
使用 FastAPI + PostgreSQL 连接扣子数据库

数据库架构：
- 开发环境：扣子平台自动注入 DATABASE_URL（开发环境数据库）
- 生产环境：扣子平台自动注入 DATABASE_URL（生产环境数据库）
- 环境切换由扣子平台自动处理，无需手动配置
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

# 环境变量说明
# ========================================
# 扣子平台会自动注入以下环境变量：
# - DATABASE_URL: PostgreSQL 连接字符串
# - PGDATABASE, PGHOST, PGPORT, PGUSER, PGPASSWORD: 分离的连接参数
#
# 无需手动配置，平台会根据环境（开发/生产）自动切换
# ========================================

# 打印启动信息
print(f"[ENV] DATABASE_URL = {'已设置' if os.getenv('DATABASE_URL') else '未设置'}")
print(f"[ENV] PGHOST = {os.getenv('PGHOST', '未设置')}")

# 导入其他模块
import logging
import uuid
import secrets
import csv
import io
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from urllib.parse import quote
from fastapi import FastAPI, HTTPException, Query, Request, File, UploadFile, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# 北京时区 (UTC+8)
BEIJING_TZ = timezone(timedelta(hours=8))


def get_beijing_time() -> datetime:
    """获取当前北京时间（带时区信息）"""
    return datetime.now(BEIJING_TZ)


def beijing_time_iso() -> str:
    """获取当前北京时间的 ISO 格式字符串（带时区信息）"""
    return datetime.now(BEIJING_TZ).isoformat()


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
    logger.info(f"[STARTUP] ENV - DATABASE_URL: {'已设置' if os.getenv('DATABASE_URL') else '未设置'}")
    logger.info(f"[STARTUP] ENV - PGHOST: {os.getenv('PGHOST', '未设置')}")
    
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
        
        # 同步主键序列（防止因数据迁移等原因导致序列不同步）
        try:
            from storage.database.postgres_client import get_postgres_client
            pg_client = get_postgres_client()
            pg_client.sync_sequence()
            logger.info("[STARTUP] 主键序列同步完成")
        except Exception as seq_err:
            logger.warning(f"[STARTUP] 主键序列同步失败（非致命错误）: {str(seq_err)}")
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
                    content={"success": False, "msg": "未授权访问，请先登录", "detail": "未授权访问，请先登录"}
                )
            
            # 检查token是否过期
            if datetime.now() > VALID_TOKENS[token]:
                del VALID_TOKENS[token]
                return JSONResponse(
                    status_code=401,
                    content={"success": False, "msg": "登录已过期，请重新登录", "detail": "登录已过期，请重新登录"}
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
    card_type_id: Optional[int] = None  # 卡种ID
    status: int = 1
    user_note: Optional[str] = ""
    feishu_url: Optional[str] = ""
    feishu_password: Optional[str] = ""
    link_name: Optional[str] = ""
    expire_days: Optional[int] = None  # 有效期天数（旧字段，兼容）
    expire_type: Optional[str] = None  # 过期类型：fixed, relative, permanent
    expire_at: Optional[str] = None  # 固定过期时间
    expire_after_days: Optional[int] = None  # 激活后有效天数
    max_uses: int = 1  # 最大使用次数
    max_devices: int = 5  # 最大设备数
    sale_status: Optional[str] = "unsold"  # 销售状态
    order_id: Optional[str] = ""  # 订单号
    sales_channel: Optional[str] = ""  # 销售渠道


class CardKeyUpdate(BaseModel):
    """更新卡密"""
    key_value: Optional[str] = None
    status: Optional[int] = None
    user_note: Optional[str] = None
    feishu_url: Optional[str] = None
    feishu_password: Optional[str] = None
    link_name: Optional[str] = None
    expire_at: Optional[str] = None
    expire_after_days: Optional[int] = None  # 激活后有效天数
    max_uses: Optional[int] = None
    max_devices: Optional[int] = None  # 最大设备数
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
    expire_type: Optional[str] = None  # 过期类型：fixed=固定日期, relative=按激活天数, permanent=永久
    expire_at: Optional[str] = None  # 过期时间（ISO格式）
    expire_after_days: Optional[int] = None  # 激活后有效天数
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


class ChangePasswordRequest(BaseModel):
    """修改密码请求"""
    old_password: str
    new_password: str


# ==================== 卡种管理 API 模型 ====================

class CardTypeCreate(BaseModel):
    """创建卡种（简化版：仅分组统计容器 + 预览配置）"""
    # 基础信息
    name: str
    
    # 预览设置
    preview_image: Optional[str] = None  # 预览截图URL（兼容旧接口）
    preview_image_id: Optional[int] = None  # 预览图片ID（新接口）
    preview_enabled: bool = False  # 是否启用预览


class CardTypeUpdate(BaseModel):
    """更新卡种（简化版：仅分组统计容器 + 预览配置）"""
    # 基础信息
    name: Optional[str] = None
    
    # 预览设置
    preview_image: Optional[str] = None  # 预览截图URL（兼容旧接口）
    preview_image_id: Optional[int] = None  # 预览图片ID（新接口）
    preview_enabled: Optional[bool] = None  # 是否启用预览
    
    # 状态
    status: Optional[int] = None


class CardKeyCreateV2(BaseModel):
    """创建卡密（新版，支持卡种和过期方式）"""
    key_value: str
    card_type_id: Optional[int] = None  # 卡种ID
    status: int = 1
    user_note: Optional[str] = ""
    feishu_url: Optional[str] = ""
    feishu_password: Optional[str] = ""
    link_name: Optional[str] = ""
    expire_at: Optional[str] = None  # 固定过期时间
    expire_after_days: Optional[int] = None  # 激活后有效天数
    max_devices: int = 5
    sale_status: Optional[str] = "unsold"
    order_id: Optional[str] = ""
    sales_channel: Optional[str] = ""


class BatchGenerateRequestV2(BaseModel):
    """批量生成卡密请求（新版，支持卡种和过期方式）"""
    count: int  # 生成数量
    prefix: str = "CSS"  # 卡密前缀
    card_type_id: Optional[int] = None  # 卡种ID（可选）
    feishu_url: str = ""  # 飞书链接
    feishu_password: str = ""  # 飞书密码
    link_name: str = ""  # 链接名称
    expire_type: Optional[str] = None  # 过期类型：fixed=固定日期, relative=按激活天数, permanent=永久, None=继承卡种设置
    expire_at: Optional[str] = None  # 过期时间（expire_type=fixed时必填）
    expire_after_days: Optional[int] = None  # 激活后有效天数（expire_type=relative时必填）
    max_devices: int = 5  # 最大设备数
    user_note: str = ""  # 备注
    sales_channel: str = ""  # 销售渠道


# ==================== 管理员认证 ====================

# 管理员密码（从环境变量读取，默认为 QJM150）
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "QJM150")

# 存储有效的 token（生产环境应使用 Redis 等）
VALID_TOKENS = {}

# Token 有效期（24小时）
TOKEN_EXPIRE_HOURS = 24


def get_admin_password() -> str:
    """获取管理员密码（优先从数据库获取，否则使用环境变量）"""
    try:
        client = get_supabase_client()
        result = client.table('admin_settings').select('value').eq('key', 'admin_password').execute()
        if result.data and len(result.data) > 0:
            return result.data[0]['value']
    except Exception as e:
        logger.warning(f"获取数据库密码失败，使用环境变量密码: {str(e)}")
    return ADMIN_PASSWORD


def set_admin_password(new_password: str) -> bool:
    """设置管理员密码到数据库"""
    try:
        client = get_supabase_client()
        # 先尝试更新
        result = client.table('admin_settings').update({'value': new_password}).eq('key', 'admin_password').execute()
        if not result.data:
            # 如果没有更新到，说明记录不存在，尝试插入
            client.table('admin_settings').insert({'key': 'admin_password', 'value': new_password}).execute()
        return True
    except Exception as e:
        logger.error(f"设置管理员密码失败: {str(e)}")
        return False


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


class UnifiedHTTPException(Exception):
    """统一格式的HTTP异常，用于返回一致的错误响应格式"""
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message


@app.exception_handler(UnifiedHTTPException)
async def unified_http_exception_handler(request: Request, exc: UnifiedHTTPException):
    """统一处理自定义异常，返回一致的响应格式"""
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "msg": exc.message, "detail": exc.message}
    )


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
        raise UnifiedHTTPException(status_code=401, message="未授权访问，请先登录")
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


def calculate_is_expired(card: dict) -> bool:
    """
    计算卡密是否已过期（实时计算）
    
    过期判断逻辑：
    1. 如果 expire_at 存在：expire_at < 当前时间 → 已过期
    2. 如果 expire_after_days 存在且 activated_at 存在：
       activated_at + expire_after_days 天 < 当前时间 → 已过期
    3. 其他情况：未过期（永久有效或未激活）
    
    Args:
        card: 卡密记录字典
        
    Returns:
        bool: True=已过期，False=未过期
    """
    now = datetime.now()
    
    # 情况1：固定日期过期
    if card.get('expire_at'):
        try:
            expire_at = datetime.fromisoformat(str(card['expire_at']).replace('Z', '+00:00'))
            # 移除时区信息进行比较
            if expire_at.tzinfo:
                expire_at = expire_at.replace(tzinfo=None)
            if expire_at < now:
                return True
        except Exception as e:
            logger.warning(f"解析expire_at失败: {card.get('expire_at')}, 错误: {e}")
    
    # 情况2：激活后N天过期
    if card.get('expire_after_days') and card.get('activated_at'):
        try:
            activated_at = datetime.fromisoformat(str(card['activated_at']).replace('Z', '+00:00'))
            # 移除时区信息
            if activated_at.tzinfo:
                activated_at = activated_at.replace(tzinfo=None)
            # 计算过期时间
            expire_date = activated_at + timedelta(days=card['expire_after_days'])
            if expire_date < now:
                return True
        except Exception as e:
            logger.warning(f"解析activated_at失败: {card.get('activated_at')}, 错误: {e}")
    
    # 未过期
    return False


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


# ==================== 预览转化模式 API ====================

@app.get("/api/preview/by-link/{link_name}")
async def get_card_type_preview_by_link(link_name: str):
    """
    根据链接名称获取卡种预览信息
    - 用于从飞书链接名称反向查找卡种
    """
    try:
        client = get_supabase_client()
        
        # 先查找卡密获取卡种ID
        card_response = client.table('card_keys_table').select('card_type_id').eq('link_name', link_name).execute()
        
        if not card_response.data:
            return {"success": False, "msg": "未找到对应卡种"}
        
        # 过滤掉没有卡种ID的记录
        card_with_type = None
        for card in card_response.data:
            if card.get('card_type_id'):
                card_with_type = card
                break
        
        if not card_with_type:
            return {"success": False, "msg": "未找到对应卡种"}
        
        card_type_id = card_with_type['card_type_id']
        
        # 获取卡种信息
        response = client.table('card_types').select('id, name, preview_image, preview_enabled, status').eq('id', card_type_id).is_('deleted_at', 'null').execute()
        
        if not response.data:
            return {"success": False, "msg": "卡种不存在"}
        
        card_type = response.data[0]
        
        # 检查是否启用预览
        if not card_type.get('preview_enabled'):
            return {"success": False, "msg": "该卡种未启用预览"}
        
        return {
            "success": True,
            "data": {
                "id": card_type['id'],
                "name": card_type['name'],
                "preview_image": card_type.get('preview_image'),
                "preview_enabled": card_type.get('preview_enabled', False)
            }
        }
        
    except Exception as e:
        logger.error(f"根据链接名称获取卡种预览信息失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.get("/api/global-preview")
async def get_global_preview_public():
    """
    获取全局预览图设置（公开接口，无需登录）
    - 用于首页默认预览展示
    """
    try:
        client = get_supabase_client()
        result = client.table('admin_settings').select('value').eq('key', 'global_preview').execute()
        if result.data and len(result.data) > 0:
            import json
            try:
                data = json.loads(result.data[0]['value'])
                if data.get('enabled'):
                    image_key = data.get('image_key', '')
                    preview_url = data.get('preview_image', '')
                    
                    # 如果存储的是 key，动态生成 URL
                    if image_key and not image_key.startswith('http') and not image_key.startswith('data:'):
                        import os
                        from coze_coding_dev_sdk.s3 import S3SyncStorage
                        
                        storage = S3SyncStorage(
                            endpoint_url=os.getenv("COZE_BUCKET_ENDPOINT_URL"),
                            access_key="",
                            secret_key="",
                            bucket_name=os.getenv("COZE_BUCKET_NAME"),
                            region="cn-beijing",
                        )
                        preview_url = storage.generate_presigned_url(key=image_key, expire_time=86400)
                    
                    if preview_url:
                        return {
                            "success": True,
                            "data": {
                                "preview_image": preview_url,
                                "enabled": True
                            }
                        }
            except:
                pass
        return {"success": True, "data": {"preview_image": None, "enabled": False}}
    except Exception as e:
        logger.error(f"获取全局预览图失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.get("/api/preview/{card_type_id}")
async def get_card_type_preview(card_type_id: int):
    """
    根据卡种ID获取预览信息
    - 用于预览转化模式
    - 无需验证即可访问
    """
    try:
        client = get_supabase_client()
        
        # 获取卡种信息
        response = client.table('card_types').select('id, name, preview_image, preview_image_id, preview_enabled, status').eq('id', card_type_id).is_('deleted_at', 'null').execute()
        
        if not response.data:
            return {"success": False, "msg": "卡种不存在"}
        
        card_type = response.data[0]
        
        # 检查卡种状态
        if card_type.get('status') != 1:
            return {"success": False, "msg": "该卡种已停用"}
        
        # 检查是否启用预览
        if not card_type.get('preview_enabled'):
            return {"success": False, "msg": "该卡种未启用预览"}
        
        # 动态生成预览图 URL
        preview_image_key = card_type.get('preview_image')
        preview_image_url = preview_image_key
        
        if preview_image_key and not preview_image_key.startswith('http') and not preview_image_key.startswith('data:'):
            import os
            from coze_coding_dev_sdk.s3 import S3SyncStorage
            
            storage = S3SyncStorage(
                endpoint_url=os.getenv("COZE_BUCKET_ENDPOINT_URL"),
                access_key="",
                secret_key="",
                bucket_name=os.getenv("COZE_BUCKET_NAME"),
                region="cn-beijing",
            )
            preview_image_url = storage.generate_presigned_url(key=preview_image_key, expire_time=86400)
        
        return {
            "success": True,
            "data": {
                "id": card_type['id'],
                "name": card_type['name'],
                "preview_image": preview_image_url,
                "preview_enabled": card_type.get('preview_enabled', False)
            }
        }
        
    except Exception as e:
        logger.error(f"获取卡种预览信息失败: {str(e)}")
        return {"success": False, "msg": str(e)}


# ==================== 验证 API ====================

class LogoutRequest(BaseModel):
    """退出登录请求"""
    card_key: str
    device_id: str = "unknown"


@app.post("/api/logout")
async def logout_card_key(request: LogoutRequest):
    """
    退出登录 API
    - 解除设备绑定
    - 记录退出日志
    """
    client = None
    card_key = request.card_key.strip().upper()
    device_id = request.device_id or "unknown"
    
    try:
        if not card_key:
            return {"success": False, "msg": "卡密不能为空"}
        
        logger.info(f"[Logout] 退出登录: {card_key}, 设备: {device_id}")
        
        # 获取数据库客户端
        try:
            client = get_supabase_client()
        except Exception as db_err:
            logger.error(f"[Logout] 数据库连接失败: {str(db_err)}")
            return {"success": False, "msg": "数据库连接失败"}
        
        # 查询卡密
        response = client.table('card_keys_table').select('id, devices').eq('key_value', card_key).execute()
        
        if not response.data:
            return {"success": False, "msg": "卡密不存在"}
        
        card_data = response.data[0]
        card_id = card_data.get('id')
        devices_json = card_data.get('devices', '[]')
        
        # 解析已绑定设备
        try:
            bound_devices = json.loads(devices_json) if devices_json else []
        except:
            bound_devices = []
        
        # 从绑定列表中移除当前设备
        if device_id in bound_devices:
            bound_devices.remove(device_id)
            logger.info(f"[Logout] 移除设备绑定: {device_id}, 剩余设备: {bound_devices}")
            
            # 更新数据库
            client.table('card_keys_table').update({
                "devices": json.dumps(bound_devices)
            }).eq('id', card_id).execute()
            
            # 记录退出日志
            log_access(client, card_id, card_key, True, "用户主动退出登录", device_id, "", False)
            
            return {"success": True, "msg": "退出登录成功", "remaining_devices": len(bound_devices)}
        else:
            # 设备未绑定，无需处理
            logger.info(f"[Logout] 设备未绑定: {device_id}")
            return {"success": True, "msg": "退出登录成功", "remaining_devices": len(bound_devices)}
        
    except Exception as e:
        logger.error(f"[Logout] 退出登录失败: {str(e)}")
        return {"success": False, "msg": str(e)}


class UnbindDeviceRequest(BaseModel):
    """解绑设备请求"""
    card_key: str
    device_id: str


@app.post("/api/unbind-device")
async def unbind_device(request: UnbindDeviceRequest):
    """
    解绑设备 API
    - 从卡密中移除指定设备绑定
    """
    client = None
    card_key = request.card_key.strip().upper()
    device_id = request.device_id
    
    try:
        if not card_key or not device_id:
            return {"success": False, "msg": "参数不完整"}
        
        logger.info(f"[Unbind] 解绑设备: {card_key}, 设备: {device_id}")
        
        client = get_supabase_client()
        
        # 查询卡密
        response = client.table('card_keys_table').select('id, devices, max_devices').eq('key_value', card_key).execute()
        
        if not response.data:
            return {"success": False, "msg": "卡密不存在"}
        
        card_data = response.data[0]
        card_id = card_data.get('id')
        devices_json = card_data.get('devices', '[]')
        max_devices = card_data.get('max_devices', 5)
        
        # 解析已绑定设备
        try:
            bound_devices = json.loads(devices_json) if devices_json else []
        except:
            bound_devices = []
        
        # 移除指定设备
        if device_id in bound_devices:
            bound_devices.remove(device_id)
            client.table('card_keys_table').update({
                "devices": json.dumps(bound_devices)
            }).eq('id', card_id).execute()
            
            logger.info(f"[Unbind] 设备解绑成功: {device_id}")
            return {
                "success": True,
                "msg": "解绑成功",
                "remaining_devices": len(bound_devices),
                "max_devices": max_devices
            }
        else:
            return {"success": False, "msg": "设备未绑定"}
        
    except Exception as e:
        logger.error(f"[Unbind] 解绑设备失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.post("/api/clear-all-devices")
async def clear_all_devices(card_key: str):
    """
    清除所有设备绑定 API
    - 重置卡密的设备绑定列表
    """
    client = None
    card_key = card_key.strip().upper()
    
    try:
        if not card_key:
            return {"success": False, "msg": "卡密不能为空"}
        
        logger.info(f"[ClearDevices] 清除所有设备绑定: {card_key}")
        
        client = get_supabase_client()
        
        # 查询卡密
        response = client.table('card_keys_table').select('id, devices').eq('key_value', card_key).execute()
        
        if not response.data:
            return {"success": False, "msg": "卡密不存在"}
        
        card_data = response.data[0]
        card_id = card_data.get('id')
        devices_json = card_data.get('devices', '[]')
        
        # 解析已绑定设备数量
        try:
            bound_devices = json.loads(devices_json) if devices_json else []
            removed_count = len(bound_devices)
        except:
            removed_count = 0
        
        # 清空设备绑定
        client.table('card_keys_table').update({
            "devices": "[]"
        }).eq('id', card_id).execute()
        
        logger.info(f"[ClearDevices] 已清除 {removed_count} 个设备绑定")
        return {
            "success": True,
            "msg": f"已清除 {removed_count} 个设备绑定",
            "removed_count": removed_count
        }
        
    except Exception as e:
        logger.error(f"[ClearDevices] 清除设备绑定失败: {str(e)}")
        return {"success": False, "msg": str(e)}


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
        logger.info(f"[Validate] 查询访问日志: {card_key}")
        existing_logs = client.table('access_logs').select('id').eq('key_value', card_key).eq('success', True).limit(1).execute()
        if not existing_logs.data:
            is_first_access = True
        logger.info(f"[Validate] 首次访问: {is_first_access}")

        # 检查状态 (1=有效, 0=无效)
        if card_data.get('status') != 1:
            log_access(client, card_id, card_key, False, "卡密已失效", device_id, sales_channel, is_first_access)
            return ValidateResponse(can_access=False, msg="卡密已失效")

        # 检查过期时间（支持三种过期方式）
        expire_at = card_data.get('expire_at')
        expire_after_days = card_data.get('expire_after_days')
        activated_at = card_data.get('activated_at')
        
        # 判断是否已过期
        is_expired = False
        expire_reason = ""
        
        now = datetime.now()
        
        # 方式1: 固定日期过期
        if expire_at:
            try:
                if hasattr(expire_at, 'tzinfo'):
                    expire_time = expire_at
                elif 'T' in str(expire_at):
                    expire_time = datetime.fromisoformat(str(expire_at).replace('Z', '+00:00'))
                elif '+' in str(expire_at) or str(expire_at).count('-') > 2:
                    expire_time = datetime.fromisoformat(str(expire_at))
                else:
                    expire_time = datetime.fromisoformat(str(expire_at))
                    expire_time = expire_time.replace(tzinfo=None)
                
                compare_now = datetime.now(expire_time.tzinfo) if expire_time.tzinfo else now
                if compare_now > expire_time:
                    is_expired = True
                    expire_reason = "卡密已过期"
            except Exception as e:
                logger.warning(f"[Validate] 解析过期时间失败: {expire_at}, 错误: {str(e)}")
        
        # 方式2: 按激活天数过期
        elif expire_after_days and activated_at:
            try:
                if hasattr(activated_at, 'tzinfo'):
                    activated_time = activated_at
                elif 'T' in str(activated_at):
                    activated_time = datetime.fromisoformat(str(activated_at).replace('Z', '+00:00'))
                else:
                    activated_time = datetime.fromisoformat(str(activated_at))
                    activated_time = activated_time.replace(tzinfo=None)
                
                compare_now = datetime.now(activated_time.tzinfo) if activated_time.tzinfo else now
                expire_time = activated_time + timedelta(days=expire_after_days)
                
                if compare_now > expire_time:
                    is_expired = True
                    expire_reason = f"卡密已过期（激活后{expire_after_days}天有效）"
            except Exception as e:
                logger.warning(f"[Validate] 解析激活时间失败: {activated_at}, 错误: {str(e)}")
        
        # 方式3: 永久有效（expire_at为空且expire_after_days为空）
        # 无需处理，is_expired保持False
        
        if is_expired:
            log_access(client, card_id, card_key, False, expire_reason, device_id, sales_channel, is_first_access)
            return ValidateResponse(can_access=False, msg=expire_reason)

        # 检查设备限制（最多5台设备）
        max_devices = card_data.get('max_devices', 5)
        devices_json = card_data.get('devices', '[]')
        logger.info(f"[Validate] 设备限制: {max_devices}, 当前设备: {devices_json}")
        
        try:
            bound_devices = json.loads(devices_json) if devices_json else []
        except:
            bound_devices = []
        
        # 检查设备是否已绑定
        device_already_bound = device_id in bound_devices
        logger.info(f"[Validate] 设备已绑定: {device_already_bound}, 设备ID: {device_id}")
        
        if not device_already_bound:
            # 新设备，检查是否达到设备限制
            if len(bound_devices) >= max_devices:
                log_access(client, card_id, card_key, False, f"设备数量已达上限({max_devices}台)", device_id, sales_channel, is_first_access)
                return ValidateResponse(can_access=False, msg=f"该卡密已在{max_devices}台设备上使用，无法在新设备登录")
            
            # 添加新设备
            logger.info(f"[Validate] 添加新设备: {device_id}")
            bound_devices.append(device_id)
            
            # 更新数据：设备绑定 + 最后使用时间 + 首次激活时间（如果是首次激活）
            update_data = {
                "devices": json.dumps(bound_devices),
                "last_used_at": now.isoformat()
            }
            
            # 首次绑定设备时，始终记录激活时间（用于判断"已激活"状态）
            # 即使后续设备全部退出，activated_at 仍存在，状态仍为"已激活"
            if not activated_at:
                update_data["activated_at"] = now.isoformat()
                logger.info(f"[Validate] 设置首次激活时间")
                if expire_after_days:
                    logger.info(f"[Validate] 按激活天数过期，{expire_after_days}天后过期")
            
            client.table('card_keys_table').update(update_data).eq('id', card_id).execute()
            logger.info(f"[Validate] 设备绑定成功")
        else:
            # 已绑定设备，只更新最后使用时间
            logger.info(f"[Validate] 更新最后使用时间")
            client.table('card_keys_table').update({
                "last_used_at": now.isoformat()
            }).eq('id', card_id).execute()
            logger.info(f"[Validate] 更新成功")

        # 记录成功日志（含行为数据）
        log_access(client, card_id, card_key, True, "验证成功", device_id, sales_channel, is_first_access)

        # 获取飞书链接和密码，确保不为 None（Pydantic 验证要求 str 类型）
        feishu_url = card_data.get('feishu_url') or ''
        feishu_password = card_data.get('feishu_password') or ''
        
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
        import traceback
        logger.error(f"验证失败: {str(e)}")
        logger.error(f"验证失败堆栈: {traceback.format_exc()}")
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
    sales_channel: Optional[str] = None,  # 销售渠道筛选
    card_type_id: Optional[int] = None,  # 卡种筛选
    key_value: Optional[str] = None  # 卡密值精确查询（用于设备管理弹窗）
):
    """获取卡密列表"""
    try:
        client = get_supabase_client()
        
        # 处理搜索参数（去除前后空格）
        if search:
            search = search.strip()
        
        query = client.table('card_keys_table').select('*', count='exact')
        
        # 卡密值精确查询（优先级最高，用于设备管理弹窗等场景）
        if key_value:
            query = query.eq('key_value', key_value.upper())
        
        # 卡种筛选
        if card_type_id:
            query = query.eq('card_type_id', card_type_id)
        
        # 搜索支持：卡密、备注、订单号、链接名称、销售渠道
        # 注意：Supabase 的 or_() 与 eq() 组合时需要特殊处理
        # 当搜索词可能匹配不到任何结果时，直接在应用层过滤会更稳定
        need_search_filter = False
        if search:
            # 先执行查询，然后在应用层过滤
            # 这样可以避免 Supabase or_() 与 eq() 组合时的语法问题
            need_search_filter = True
            logger.info(f"[搜索] 搜索关键词: {search} (应用层过滤)")
        
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
            if sales_channel == '未设置':
                # 特殊值：筛选未设置销售渠道的记录（空值或空字符串）
                query = query.or_('sales_channel.is.null,sales_channel.eq.')
            else:
                query = query.eq('sales_channel', sales_channel)
        
        if sale_status:
            if sale_status == '__none__':
                # 特殊值：筛选未设置销售状态的记录（空值或空字符串）
                query = query.or_('sale_status.is.null,sale_status.eq.')
            else:
                # 映射中文值到英文
                sale_status_map = {
                    '未销售': 'unsold',
                    '已售出': 'sold',
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
            if device_filter == '0':
                # 未绑定：设备列表为空
                query = query.eq('devices', '[]')
            elif device_filter == '1+':
                # 已绑定：设备列表不为空（需要在应用层过滤）
                need_device_filter = True
                device_count_filter = -1  # -1 表示筛选大于0的记录
            else:
                # 兼容旧版数字筛选
                try:
                    device_count_filter = int(device_filter)
                    if device_count_filter == 0:
                        query = query.eq('devices', '[]')
                    else:
                        need_device_filter = True
                except ValueError:
                    pass
        
        # 过期时间筛选
        need_expire_filter = False  # 是否需要在应用层过滤过期状态
        if expire_days:
            now = datetime.now()
            if expire_days == 'expired':
                # 已过期：需要在应用层过滤（包括固定日期过期和激活后N天过期）
                need_expire_filter = True
                # 查询所有可能过期的记录（有 expire_at 或 expire_after_days）
                query = query.or_('expire_at.not.is.null,expire_after_days.not.is.null')
            elif expire_days == 'permanent':
                # 永久有效：过期时间和激活后有效天数都为空
                query = query.is_('expire_at', 'null').is_('expire_after_days', 'null')
            elif expire_days.startswith('date:'):
                # 按具体日期筛选：date:2026-12-31
                target_date = expire_days[5:]  # 去掉 'date:' 前缀
                # 匹配该日期的过期时间（00:00:00 ~ 23:59:59）
                start_time = f"{target_date}T00:00:00"
                end_time = f"{target_date}T23:59:59"
                query = query.not_().is_('expire_at', 'null').gte('expire_at', start_time).lte('expire_at', end_time)
            elif expire_days.startswith('relative:'):
                # 激活后N天有效：relative:60
                days = int(expire_days[9:])  # 去掉 'relative:' 前缀
                query = query.eq('expire_after_days', days)
            else:
                # 未来N天内过期：过期时间在当前时间和N天后之间
                try:
                    days = int(expire_days)
                    future_date = (now + timedelta(days=days)).isoformat()
                    query = query.not_().is_('expire_at', 'null').gte('expire_at', now.isoformat()).lte('expire_at', future_date)
                except ValueError:
                    pass
        
        # 如果需要在应用层过滤设备数量、激活状态、过期状态或搜索，先获取所有数据再过滤
        if need_device_filter or need_activate_filter or need_expire_filter or need_search_filter:
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
                        device_len = len(devices)
                        if device_count_filter == -1:
                            # -1 表示已绑定（设备数 > 0）
                            if device_len == 0:
                                continue
                        elif device_len != device_count_filter:
                            continue
                    except:
                        if device_count_filter == -1:
                            # 解析失败，视为无设备
                            continue
                        elif device_count_filter != 0:
                            continue
                
                # 激活状态过滤（需要处理 NULL 值）
                if need_activate_filter:
                    sale_status = card.get('sale_status')
                    # 排除销售状态为 refunded/disputed 的记录（但允许 NULL）
                    if sale_status in ['refunded', 'disputed']:
                        continue
                    
                    card_status = card.get('status', 1)
                    card_activated_at = card.get('activated_at')
                    
                    if activate_status == 'valid':
                        # 有效：status=1 且 从未激活过（activated_at 为空）
                        if card_status == 0 or card_activated_at:
                            continue
                    
                    elif activate_status == 'activated':
                        # 已激活：曾经绑定过设备（activated_at 不为空）
                        if not card_activated_at:
                            continue
                    
                    elif activate_status == 'disabled':
                        # 已停用：status=0 或 销售状态为refunded/disputed
                        if card_status != 0 and sale_status not in ['refunded', 'disputed']:
                            continue
                
                # 过期状态过滤
                if need_expire_filter:
                    # 使用统一的过期判断函数
                    if not calculate_is_expired(card):
                        continue
                
                # 搜索过滤（模糊匹配多个字段）
                if need_search_filter:
                    search_lower = search.lower()
                    match_fields = [
                        card.get('key_value', ''),
                        card.get('user_note', ''),
                        card.get('order_id', ''),
                        card.get('link_name', ''),
                        card.get('sales_channel', '')
                    ]
                    # 检查是否有任一字段匹配搜索词
                    matched = any(search_lower in str(field).lower() for field in match_fields)
                    if not matched:
                        continue
                
                filtered_data.append(card)
            
            # 手动分页
            total = len(filtered_data)
            total_pages = (total + page_size - 1) // page_size if total else 0
            start = (page - 1) * page_size
            end = start + page_size
            paginated_data = filtered_data[start:end]
            
            # 为每条记录添加 is_expired 字段（实时计算）
            for card in paginated_data:
                card['is_expired'] = calculate_is_expired(card)
            
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
        
        # 为每条记录添加 is_expired 字段（实时计算）
        for card in response.data:
            card['is_expired'] = calculate_is_expired(card)
        
        logger.info(f"[搜索结果] 返回数据条数: {len(response.data)}, 总数: {response.count}")
        
        return {
            "success": True,
            "data": response.data,
            "total": response.count,
            "page": page,
            "page_size": page_size,
            "total_pages": (response.count + page_size - 1) // page_size if response.count else 0
        }
        
    except Exception as e:
        import traceback
        logger.error(f"获取卡密列表失败: {str(e)}")
        logger.error(f"详细堆栈: {traceback.format_exc()}")
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
        
        # 为每条记录添加 is_expired 字段（实时计算）
        for card in response.data:
            card['is_expired'] = calculate_is_expired(card)
        
        return {"success": True, "data": response.data}
        
    except Exception as e:
        logger.error(f"根据ID获取卡密失败: {str(e)}")
        return {"success": False, "msg": str(e)}


# ==================== 卡种管理 API ====================

@app.get("/api/admin/card-types")
async def get_card_types(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    status: Optional[int] = None
):
    """获取卡种列表（包含销售统计信息）- 优化版：避免N+1查询"""
    try:
        client = get_supabase_client()
        
        # 处理搜索参数
        if search:
            search = search.strip()
        
        # 构建查询
        query = client.table('card_types').select('*', count='exact')
        
        # 排除已删除的
        query = query.is_('deleted_at', 'null')
        
        if search:
            query = query.ilike('name', f'%{search}%')
        
        if status is not None:
            query = query.eq('status', status)
        
        # 分页
        start = (page - 1) * page_size
        end = start + page_size - 1
        
        response = query.range(start, end).order('id', desc=True).execute()
        
        # 获取卡种列表
        card_types = response.data or []
        
        if not card_types:
            return {
                "success": True,
                "data": [],
                "total": 0,
                "page": page,
                "page_size": page_size,
                "total_pages": 0
            }
        
        # 【优化】一次性获取所有相关卡种的统计数据，避免N+1查询
        card_type_ids = [ct['id'] for ct in card_types]
        
        # 一次性查询所有卡密的统计数据
        all_cards_response = client.table('card_keys_table').select(
            'id, card_type_id, status, sale_status, devices, expire_at, expire_after_days, activated_at'
        ).in_('card_type_id', card_type_ids).execute()
        
        # 在内存中按卡种ID分组统计
        now = datetime.now()
        
        # 初始化每个卡种的统计容器
        stats_by_type = {}
        for type_id in card_type_ids:
            stats_by_type[type_id] = {
                'total_count': 0,
                'unsold_count': 0,
                'sold_count': 0,
                'refunded_count': 0,
                'disputed_count': 0,
                'stock_count': 0,
                'activated_count': 0,
                'deactivated_count': 0,
                'expired_count': 0
            }
        
        # 遍历所有卡密，按卡种ID分组统计
        for card in (all_cards_response.data or []):
            type_id = card.get('card_type_id')
            if type_id not in stats_by_type:
                continue
            
            stats = stats_by_type[type_id]
            stats['total_count'] += 1
            
            # 统计卡密状态（激活/停用）
            card_status = card.get('status', 1)
            sale_status = card.get('sale_status', 'unsold')
            card_activated_at = card.get('activated_at')
            
            # 判断销售状态是否正常
            is_sale_normal = sale_status not in ['refunded', 'disputed']
            
            # 统计已停用：status=0 或 销售状态为refunded/disputed
            if card_status == 0 or not is_sale_normal:
                stats['deactivated_count'] += 1
            elif card_activated_at:
                # 已激活：曾经绑定过设备（activated_at 不为空）
                stats['activated_count'] += 1
            else:
                # 库存：从未激活过
                stats['stock_count'] += 1
            
            # 统计销售状态
            sale_status = card.get('sale_status', 'unsold')
            if sale_status == 'unsold':
                stats['unsold_count'] += 1
            elif sale_status == 'sold':
                stats['sold_count'] += 1
            elif sale_status == 'refunded':
                stats['refunded_count'] += 1
            elif sale_status == 'disputed':
                stats['disputed_count'] += 1
            
            # 统计已过期
            expire_at = card.get('expire_at')
            expire_after_days = card.get('expire_after_days')
            activated_at = card.get('activated_at')
            
            if expire_at:
                try:
                    if isinstance(expire_at, str):
                        expire_time = datetime.fromisoformat(expire_at.replace('Z', '+00:00'))
                    else:
                        expire_time = expire_at
                    if expire_time.tzinfo:
                        expire_time = expire_time.replace(tzinfo=None)
                    if expire_time < now:
                        stats['expired_count'] += 1
                except:
                    pass
            elif expire_after_days and activated_at:
                try:
                    if isinstance(activated_at, str):
                        activated_time = datetime.fromisoformat(activated_at.replace('Z', '+00:00'))
                    else:
                        activated_time = activated_at
                    if activated_time.tzinfo:
                        activated_time = activated_time.replace(tzinfo=None)
                    expire_time = activated_time + timedelta(days=expire_after_days)
                    if expire_time < now:
                        stats['expired_count'] += 1
                except:
                    pass
        
        # 将统计数据合并到卡种列表中
        for card_type in card_types:
            type_id = card_type['id']
            stats = stats_by_type.get(type_id, {})
            card_type['total_count'] = stats.get('total_count', 0)
            card_type['unsold_count'] = stats.get('unsold_count', 0)
            card_type['sold_count'] = stats.get('sold_count', 0)
            card_type['refunded_count'] = stats.get('refunded_count', 0)
            card_type['disputed_count'] = stats.get('disputed_count', 0)
            card_type['stock_count'] = stats.get('stock_count', 0)
            card_type['expired_count'] = stats.get('expired_count', 0)
            card_type['activated_count'] = stats.get('activated_count', 0)
            card_type['deactivated_count'] = stats.get('deactivated_count', 0)
        
        return {
            "success": True,
            "data": card_types,
            "total": response.count or 0,
            "page": page,
            "page_size": page_size,
            "total_pages": ((response.count or 0) + page_size - 1) // page_size
        }
        
    except Exception as e:
        logger.error(f"获取卡种列表失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.get("/api/admin/card-types/options")
async def get_card_types_options():
    """获取卡种选项列表（用于下拉选择）"""
    try:
        client = get_supabase_client()
        
        # 获取所有有效的卡种
        response = client.table('card_types').select('id, name').eq('status', 1).is_('deleted_at', 'null').order('name').execute()
        
        return {"success": True, "data": response.data or []}
        
    except Exception as e:
        logger.error(f"获取卡种选项失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.post("/api/admin/card-types")
async def create_card_type(card_type: CardTypeCreate):
    """创建卡种（简化版）"""
    try:
        client = get_supabase_client()
        
        # 检查名称是否已存在
        existing = client.table('card_types').select('id').eq('name', card_type.name).is_('deleted_at', 'null').execute()
        if existing.data:
            return {"success": False, "msg": "卡种名称已存在"}
        
        # 创建卡种 - 只包含数据库中确定存在的字段
        data = {
            "name": card_type.name,
            "preview_enabled": card_type.preview_enabled,
            "status": 1,
            "created_at": beijing_time_iso()
        }
        
        # 预览图片处理：根据 preview_image_id 获取 image_key 存储到 preview_image 字段
        if card_type.preview_image_id:
            img_result = client.table('preview_images').select('image_key').eq('id', card_type.preview_image_id).execute()
            if img_result.data:
                data["preview_image"] = img_result.data[0].get('image_key', '')
        elif card_type.preview_image:
            data["preview_image"] = card_type.preview_image
        
        response = client.table('card_types').insert(data).execute()
        
        logger.info(f"创建卡种成功: {card_type.name}")
        
        return {"success": True, "data": response.data[0], "msg": "创建成功"}
        
    except Exception as e:
        logger.error(f"创建卡种失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.get("/api/admin/card-types/{type_id}")
async def get_card_type(type_id: int):
    """获取卡种详情"""
    try:
        client = get_supabase_client()
        
        # 获取卡种信息
        response = client.table('card_types').select('*').eq('id', type_id).is_('deleted_at', 'null').execute()
        
        if not response.data:
            return {"success": False, "msg": "卡种不存在"}
        
        card_type = response.data[0]
        
        # 动态生成预览图 URL
        preview_image_key = card_type.get('preview_image')
        if preview_image_key and not preview_image_key.startswith('http') and not preview_image_key.startswith('data:'):
            import os
            from coze_coding_dev_sdk.s3 import S3SyncStorage
            
            storage = S3SyncStorage(
                endpoint_url=os.getenv("COZE_BUCKET_ENDPOINT_URL"),
                access_key="",
                secret_key="",
                bucket_name=os.getenv("COZE_BUCKET_NAME"),
                region="cn-beijing",
            )
            card_type['preview_image_url'] = storage.generate_presigned_url(key=preview_image_key, expire_time=86400)
        else:
            card_type['preview_image_url'] = preview_image_key
        
        # 根据 preview_image (image_key) 反向查找 preview_image_id
        if preview_image_key:
            img_result = client.table('preview_images').select('id').eq('image_key', preview_image_key).execute()
            if img_result.data:
                card_type['preview_image_id'] = img_result.data[0]['id']
        
        # 获取该卡种下的卡密统计
        stats_response = client.table('card_keys_table').select('id, status, devices, expire_at, expire_after_days, activated_at, sale_status', count='exact').eq('card_type_id', type_id).execute()
        
        total_count = stats_response.count or 0
        expired_count = 0
        sold_count = 0
        activated_count = 0
        deactivated_count = 0
        stock_count = 0
        now = datetime.now()
        
        for card in (stats_response.data or []):
            # 统计状态
            card_status = card.get('status', 1)
            sale_status = card.get('sale_status', 'unsold')
            card_activated_at = card.get('activated_at')
            
            is_sale_normal = sale_status not in ['refunded', 'disputed']
            
            # 统计已停用：status=0 或 销售状态为refunded/disputed
            if card_status == 0 or not is_sale_normal:
                deactivated_count += 1
            elif card_activated_at:
                # 已激活：曾经绑定过设备（activated_at 不为空）
                activated_count += 1
            else:
                # 库存：从未激活过
                stock_count += 1
            
            # 统计已过期
            expire_at = card.get('expire_at')
            expire_after_days = card.get('expire_after_days')
            activated_at = card.get('activated_at')
            
            if expire_at:
                try:
                    if isinstance(expire_at, str):
                        expire_time = datetime.fromisoformat(expire_at.replace('Z', '+00:00'))
                    else:
                        expire_time = expire_at
                    if expire_time.tzinfo:
                        expire_time = expire_time.replace(tzinfo=None)
                    if expire_time < now:
                        expired_count += 1
                except:
                    pass
            elif expire_after_days and activated_at:
                try:
                    if isinstance(activated_at, str):
                        activated_time = datetime.fromisoformat(activated_at.replace('Z', '+00:00'))
                    else:
                        activated_time = activated_at
                    if activated_time.tzinfo:
                        activated_time = activated_time.replace(tzinfo=None)
                    expire_time = activated_time + timedelta(days=expire_after_days)
                    if expire_time < now:
                        expired_count += 1
                except:
                    pass
            
            # 统计已售出
            if card.get('sale_status') == 'sold':
                sold_count += 1
        
        card_type['stats'] = {
            'total_count': total_count,
            'stock_count': stock_count,
            'activated_count': activated_count,
            'deactivated_count': deactivated_count,
            'expired_count': expired_count,
            'sold_count': sold_count
        }
        
        return {"success": True, "data": card_type}
        
    except Exception as e:
        logger.error(f"获取卡种详情失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.put("/api/admin/card-types/{type_id}")
async def update_card_type(type_id: int, card_type: CardTypeUpdate):
    """更新卡种（简化版）"""
    try:
        client = get_supabase_client()
        
        # 检查卡种是否存在
        existing = client.table('card_types').select('id').eq('id', type_id).is_('deleted_at', 'null').execute()
        if not existing.data:
            return {"success": False, "msg": "卡种不存在"}
        
        # 构建更新数据 - 只包含数据库中存在的字段
        update_data = {}
        
        if card_type.name is not None:
            # 检查名称是否与其他卡种重复
            name_check = client.table('card_types').select('id').eq('name', card_type.name).neq('id', type_id).is_('deleted_at', 'null').execute()
            if name_check.data:
                return {"success": False, "msg": "卡种名称已存在"}
            update_data['name'] = card_type.name
        
        # 预览设置：根据 preview_image_id 获取 image_key 存储到 preview_image 字段
        if card_type.preview_image_id is not None:
            if card_type.preview_image_id:
                img_result = client.table('preview_images').select('image_key').eq('id', card_type.preview_image_id).execute()
                if img_result.data:
                    update_data['preview_image'] = img_result.data[0].get('image_key', '')
            else:
                update_data['preview_image'] = None
        elif card_type.preview_image is not None:
            update_data['preview_image'] = card_type.preview_image
        
        if card_type.preview_enabled is not None:
            update_data['preview_enabled'] = card_type.preview_enabled
        
        # 状态
        if card_type.status is not None:
            update_data['status'] = card_type.status
        
        if not update_data:
            return {"success": True, "msg": "没有需要更新的字段"}
        
        update_data['updated_at'] = beijing_time_iso()
        
        response = client.table('card_types').update(update_data).eq('id', type_id).execute()
        
        logger.info(f"更新卡种成功: ID={type_id}")
        
        return {"success": True, "data": response.data[0], "msg": "更新成功"}
        
    except Exception as e:
        logger.error(f"更新卡种失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.delete("/api/admin/card-types/{type_id}")
async def delete_card_type(type_id: int):
    """删除卡种（软删除，同时删除关联卡密）"""
    try:
        client = get_supabase_client()
        
        # 检查卡种是否存在
        existing = client.table('card_types').select('id, name').eq('id', type_id).is_('deleted_at', 'null').execute()
        if not existing.data:
            return {"success": False, "msg": "卡种不存在"}
        
        type_name = existing.data[0]['name']
        
        # 获取该卡种下的卡密ID列表
        cards_response = client.table('card_keys_table').select('id').eq('card_type_id', type_id).execute()
        card_ids = [card['id'] for card in (cards_response.data or [])]
        
        # 删除关联的访问日志
        if card_ids:
            client.table('access_logs').delete().in_('card_key_id', card_ids).execute()
            # 删除卡密
            client.table('card_keys_table').delete().eq('card_type_id', type_id).execute()
        
        # 软删除卡种
        client.table('card_types').update({
            'deleted_at': beijing_time_iso(),
            'status': 0
        }).eq('id', type_id).execute()
        
        logger.info(f"删除卡种成功: {type_name}, 删除卡密数量: {len(card_ids)}")
        
        return {"success": True, "msg": f"已删除卡种及其关联的 {len(card_ids)} 张卡密"}
        
    except Exception as e:
        logger.error(f"删除卡种失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.get("/api/admin/card-types/{type_id}/stats")
async def get_card_type_stats(type_id: int):
    """获取卡种统计数据：库存、已激活、已过期、已停用、总数"""
    try:
        client = get_supabase_client()
        
        # 检查卡种是否存在
        type_response = client.table('card_types').select('id, name').eq('id', type_id).is_('deleted_at', 'null').execute()
        if not type_response.data:
            return {"success": False, "msg": "卡种不存在"}
        
        # 获取该卡种下所有卡密的统计（包含过期判断所需字段）
        response = client.table('card_keys_table').select('status, devices, sale_status, expire_at, expire_after_days, activated_at').eq('card_type_id', type_id).execute()
        
        cards = response.data or []
        total = len(cards)
        
        # 库存（未激活）：status=1 且 devices为空 且 销售状态正常 且 未过期
        stock = 0
        activated = 0
        expired = 0
        disabled = 0
        now = datetime.now()
        
        for c in cards:
            sale_status = c.get('sale_status')
            status = c.get('status')
            devices = c.get('devices')
            
            # 计算是否已过期
            is_expired = False
            if status == 1:  # 只有有效状态的卡密才计算过期
                expire_at = c.get('expire_at')
                expire_after_days = c.get('expire_after_days')
                activated_at = c.get('activated_at')
                
                if expire_at:
                    try:
                        expire_time = datetime.fromisoformat(expire_at.replace('Z', '+00:00')) if isinstance(expire_at, str) else expire_at
                        if expire_time.tzinfo:
                            expire_time = expire_time.replace(tzinfo=None)
                        if expire_time < now:
                            is_expired = True
                    except:
                        pass
                elif expire_after_days and activated_at:
                    try:
                        activated_time = datetime.fromisoformat(activated_at.replace('Z', '+00:00')) if isinstance(activated_at, str) else activated_at
                        if activated_time.tzinfo:
                            activated_time = activated_time.replace(tzinfo=None)
                        expire_time = activated_time + timedelta(days=expire_after_days)
                        if expire_time < now:
                            is_expired = True
                    except:
                        pass
            
            # 排除销售状态为退款/纠纷的
            if sale_status in ['refunded', 'disputed']:
                disabled += 1
                continue
            
            # 已过期
            if is_expired:
                expired += 1
                continue
            
            # 已停用
            if status == 0:
                disabled += 1
                continue
            
            # 已激活：曾经绑定过设备（activated_at 不为空）
            # 这符合业务逻辑：一旦激活过，状态就应该保持，除非卡密到期或手动停用
            if c.get('activated_at'):
                activated += 1
            else:
                # 库存（从未激活过）
                stock += 1
        
        return {
            "success": True,
            "data": {
                "stock": stock,
                "activated": activated,
                "expired": expired,
                "disabled": disabled,
                "total": total
            }
        }
        
    except Exception as e:
        logger.error(f"获取卡种统计失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.get("/api/admin/card-types/{type_id}/cards")
async def get_card_type_cards(
    type_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    search: Optional[str] = None,
    status: Optional[int] = None,
    sale_status: Optional[str] = None,
    activate_status: Optional[str] = None,  # valid, activated, disabled
    expire_filter: Optional[str] = None  # expired, valid, permanent
):
    """获取卡种下的卡密列表"""
    try:
        client = get_supabase_client()
        
        # 检查卡种是否存在
        type_response = client.table('card_types').select('id, name').eq('id', type_id).is_('deleted_at', 'null').execute()
        if not type_response.data:
            return {"success": False, "msg": "卡种不存在"}
        
        card_type = type_response.data[0]
        
        # 构建查询
        query = client.table('card_keys_table').select('*', count='exact').eq('card_type_id', type_id)
        
        # 搜索 - 改为应用层过滤，避免 Supabase or_() 与 eq() 组合问题
        need_search_filter = False
        if search:
            search = search.strip()
            need_search_filter = True
        
        # 激活状态筛选
        need_activate_filter = False
        if activate_status:
            if activate_status == 'disabled':
                # 已停用：status=0 或 退款或有纠纷
                query = query.or_("status.eq.0,sale_status.in.(refunded,disputed)")
            elif activate_status == 'valid':
                # 有效：status=1 且 从未激活过（activated_at 为空）且销售状态正常
                query = query.eq('status', 1)
                query = query.is_('activated_at', 'null')
                query = query.not_().in_('sale_status', ['refunded', 'disputed'])
            elif activate_status == 'activated':
                # 已激活：曾经绑定过设备（activated_at 不为空）且销售状态正常
                query = query.eq('status', 1)
                query = query.not_().is_('activated_at', 'null')
                query = query.not_().in_('sale_status', ['refunded', 'disputed'])
        
        # 状态筛选（兼容旧参数）
        if status is not None:
            query = query.eq('status', status)
        
        # 销售状态筛选
        if sale_status:
            query = query.eq('sale_status', sale_status)
        
        # 过期筛选
        now = datetime.now()
        if expire_filter == 'expired':
            # 已过期（需要在应用层处理）
            pass
        elif expire_filter == 'valid':
            # 未过期
            query = query.or_('expire_at.is.null,expire_at.gte.' + now.isoformat())
        elif expire_filter == 'permanent':
            # 永久有效（expire_at 和 expire_after_days 都为空）
            query = query.is_('expire_at', 'null').is_('expire_after_days', 'null')
        elif expire_filter and expire_filter.startswith('date:'):
            # 指定日期到期
            target_date = expire_filter.replace('date:', '')
            query = query.gte('expire_at', f"{target_date}T00:00:00").lt('expire_at', f"{target_date}T23:59:59")
        elif expire_filter and expire_filter.startswith('relative:'):
            # 激活后N天有效
            days = int(expire_filter.replace('relative:', ''))
            query = query.eq('expire_after_days', days)
        
        # 如果需要应用层过滤（搜索或过期筛选），先获取所有数据
        if need_search_filter or expire_filter == 'expired':
            response = query.order('id', desc=True).execute()
            all_cards = response.data or []
            
            # 应用层搜索过滤
            if need_search_filter:
                search_lower = search.lower()
                filtered_cards = []
                for card in all_cards:
                    match_fields = [
                        card.get('key_value', ''),
                        card.get('user_note', ''),
                        card.get('order_id', ''),
                        card.get('link_name', ''),
                        card.get('sales_channel', '')
                    ]
                    if any(search_lower in str(field).lower() for field in match_fields):
                        filtered_cards.append(card)
                all_cards = filtered_cards
            
            # 应用层过期筛选
            if expire_filter == 'expired':
                now = datetime.now()
                expired_cards = []
                for card in all_cards:
                    expire_at = card.get('expire_at')
                    expire_after_days = card.get('expire_after_days')
                    activated_at = card.get('activated_at')
                    is_expired = False
                    
                    if expire_at:
                        try:
                            if isinstance(expire_at, str):
                                expire_time = datetime.fromisoformat(expire_at.replace('Z', '+00:00'))
                            else:
                                expire_time = expire_at
                            if expire_time.tzinfo:
                                expire_time = expire_time.replace(tzinfo=None)
                            is_expired = expire_time < now
                        except:
                            pass
                    elif expire_after_days and activated_at:
                        try:
                            if isinstance(activated_at, str):
                                activated_time = datetime.fromisoformat(activated_at.replace('Z', '+00:00'))
                            else:
                                activated_time = activated_at
                            if activated_time.tzinfo:
                                activated_time = activated_time.replace(tzinfo=None)
                            is_expired = activated_time + timedelta(days=expire_after_days) < now
                        except:
                            pass
                    
                    if is_expired:
                        expired_cards.append(card)
                all_cards = expired_cards
            
            # 手动分页
            total = len(all_cards)
            start = (page - 1) * page_size
            end = start + page_size
            cards = all_cards[start:end]
        else:
            # 分页
            start = (page - 1) * page_size
            end = start + page_size - 1
            
            response = query.range(start, end).order('id', desc=True).execute()
            cards = response.data or []
        
        # 处理过期状态（包括按激活天数过期的情况）
        now = datetime.now()
        for card in cards:
            expire_at = card.get('expire_at')
            expire_after_days = card.get('expire_after_days')
            activated_at = card.get('activated_at')
            
            # 计算实际过期时间
            actual_expire_at = None
            is_expired = False
            
            if expire_at:
                actual_expire_at = expire_at
                try:
                    if isinstance(expire_at, str):
                        expire_time = datetime.fromisoformat(expire_at.replace('Z', '+00:00'))
                    else:
                        expire_time = expire_at
                    if expire_time.tzinfo:
                        expire_time = expire_time.replace(tzinfo=None)
                    is_expired = expire_time < now
                except:
                    pass
            elif expire_after_days and activated_at:
                try:
                    if isinstance(activated_at, str):
                        activated_time = datetime.fromisoformat(activated_at.replace('Z', '+00:00'))
                    else:
                        activated_time = activated_at
                    if activated_time.tzinfo:
                        activated_time = activated_time.replace(tzinfo=None)
                    actual_expire_at = (activated_time + timedelta(days=expire_after_days)).isoformat()
                    is_expired = activated_time + timedelta(days=expire_after_days) < now
                except:
                    pass
            
            card['actual_expire_at'] = actual_expire_at
            card['is_expired'] = is_expired
        
        # 返回结果
        if need_search_filter or expire_filter == 'expired':
            # 应用层过滤时，使用已计算的 total
            return {
                "success": True,
                "data": cards,
                "card_type": card_type,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size if total else 0
            }
        else:
            return {
                "success": True,
                "data": cards,
                "card_type": card_type,
                "total": response.count or 0,
                "page": page,
                "page_size": page_size,
                "total_pages": ((response.count or 0) + page_size - 1) // page_size
            }
        
    except Exception as e:
        logger.error(f"获取卡种卡密列表失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.post("/api/admin/card-types/{type_id}/cards/batch-generate")
async def batch_generate_cards_for_type(type_id: int, req: BatchGenerateRequestV2):
    """在卡种下批量生成卡密"""
    try:
        # 验证卡种存在并获取卡种信息
        client = get_supabase_client()
        type_response = client.table('card_types').select('*').eq('id', type_id).is_('deleted_at', 'null').execute()
        if not type_response.data:
            return {"success": False, "msg": "卡种不存在"}
        
        card_type = type_response.data[0]
        
        if req.count < 1 or req.count > 1000:
            return {"success": False, "msg": "生成数量必须在 1-1000 之间"}
        
        # 确定过期方式
        expire_type = req.expire_type
        expire_at = req.expire_at
        expire_after_days = req.expire_after_days
        
        # 如果未指定过期方式，从卡种继承
        if not expire_type:
            # 从卡种获取默认配置
            expire_type = card_type.get('expire_type')
            if expire_type == 'fixed':
                expire_at = card_type.get('expire_at')
            elif expire_type == 'relative':
                expire_after_days = card_type.get('expire_after_days')
            
            # 如果卡种也没有设置过期方式，默认为永久有效
            if not expire_type:
                expire_type = 'permanent'
        
        # 验证过期方式
        if expire_type == 'fixed' and not expire_at:
            return {"success": False, "msg": "固定日期过期必须指定过期时间"}
        if expire_type == 'relative' and not expire_after_days:
            return {"success": False, "msg": "按激活天数过期必须指定有效天数"}
        
        # 获取飞书链接信息（优先使用请求参数，否则从卡种继承）
        feishu_url = req.feishu_url or card_type.get('feishu_url') or ''
        feishu_password = req.feishu_password or card_type.get('feishu_password') or ''
        link_name = req.link_name or card_type.get('link_name') or ''
        
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
            
            card_data = {
                "key_value": key,
                "card_type_id": type_id,
                "status": 1,
                "user_note": req.user_note,
                "feishu_url": feishu_url,
                "feishu_password": feishu_password,
                "link_name": link_name,
                "sys_platform": "卡密系统",
                "uuid": str(uuid.uuid4()),
                "bstudio_create_time": beijing_time_iso(),
                "max_devices": req.max_devices,
                "used_count": 0,
                "devices": "[]",
                "sales_channel": req.sales_channel,
                "sale_status": "unsold"
            }
            
            # 设置过期方式
            if expire_type == 'fixed':
                card_data["expire_at"] = expire_at
            elif expire_type == 'relative':
                card_data["expire_after_days"] = expire_after_days
            # permanent 类型不设置过期时间
            
            cards.append(card_data)
        
        # 批量插入
        response = client.table('card_keys_table').insert(cards).execute()
        generated_count = len(response.data)
        generated_ids = [card['id'] for card in response.data]
        
        # 记录操作日志
        safe_log_operation(client, {
            "operator": "admin",
            "operation_type": "batch_generate",
            "filter_conditions": {
                "card_type_id": type_id,
                "count": req.count,
                "expire_type": expire_type
            },
            "affected_count": generated_count,
            "affected_ids": generated_ids,
            "update_fields": {},
            "remark": f"在卡种ID={type_id}下批量生成 {generated_count} 条卡密"
        })
        
        return {
            "success": True,
            "data": response.data,
            "msg": f"成功生成 {generated_count} 个卡密"
        }
        
    except Exception as e:
        logger.error(f"批量生成卡密失败: {str(e)}")
        return {"success": False, "msg": str(e)}


class SimpleGenerateRequest(BaseModel):
    """简单生成卡密请求"""
    count: int = 10


@app.post("/api/admin/card-types/{type_id}/generate-cards")
async def simple_generate_cards_for_type(type_id: int, req: SimpleGenerateRequest):
    """在卡种下简单生成卡密（使用卡种默认配置）"""
    try:
        client = get_supabase_client()
        
        # 验证卡种存在
        type_response = client.table('card_types').select('*').eq('id', type_id).is_('deleted_at', 'null').execute()
        if not type_response.data:
            return {"success": False, "msg": "卡种不存在"}
        
        card_type = type_response.data[0]
        
        if req.count < 1 or req.count > 1000:
            return {"success": False, "msg": "生成数量必须在 1-1000 之间"}
        
        # 批量生成卡密
        cards = []
        generated_keys = set()
        
        for _ in range(req.count):
            while True:
                key = generate_card_key("CSS")
                if key not in generated_keys:
                    generated_keys.add(key)
                    break
            
            card_data = {
                "key_value": key,
                "card_type_id": type_id,
                "status": 1,
                "sys_platform": "卡密系统",
                "uuid": str(uuid.uuid4()),
                "bstudio_create_time": beijing_time_iso(),
                "max_devices": 5,
                "used_count": 0,
                "devices": "[]",
                "sale_status": "unsold"
            }
            cards.append(card_data)
        
        # 批量插入
        response = client.table('card_keys_table').insert(cards).execute()
        generated_count = len(response.data)
        
        return {
            "success": True,
            "data": {"created_count": generated_count},
            "msg": f"成功生成 {generated_count} 张卡密"
        }
        
    except Exception as e:
        logger.error(f"生成卡密失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.get("/api/admin/card-types/{type_id}/export")
async def export_card_type_cards(
    type_id: int,
    format: str = Query("xlsx", description="导出格式: xlsx, csv 或 txt"),
    fields: Optional[str] = Query(None, description="导出字段，逗号分隔"),
    ids: Optional[str] = Query(None, description="指定导出的卡密ID，逗号分隔"),
    search: Optional[str] = None,
    activate_status: Optional[str] = None,
    sale_status: Optional[str] = None
):
    """导出卡种下的卡密"""
    try:
        client = get_supabase_client()
        
        # 验证卡种存在
        type_response = client.table('card_types').select('name').eq('id', type_id).is_('deleted_at', 'null').execute()
        if not type_response.data:
            return {"success": False, "msg": "卡种不存在"}
        
        card_type = type_response.data[0]
        
        # 构建查询
        query = client.table('card_keys_table').select('*').eq('card_type_id', type_id)
        
        # 指定ID导出
        if ids:
            id_list = [int(id.strip()) for id in ids.split(',') if id.strip().isdigit()]
            if id_list:
                query = query.in_('id', id_list)
        
        # 搜索 - 改为应用层过滤
        need_search_filter = False
        if search:
            search = search.strip()
            need_search_filter = True
        
        # 激活状态筛选
        if activate_status:
            if activate_status == 'disabled':
                query = query.or_("status.eq.0,sale_status.in.(refunded,disputed)")
            elif activate_status == 'valid':
                # 有效：status=1 且 从未激活过（activated_at 为空）
                query = query.eq('status', 1)
                query = query.is_('activated_at', 'null')
                query = query.not_().in_('sale_status', ['refunded', 'disputed'])
            elif activate_status == 'activated':
                # 已激活：曾经绑定过设备（activated_at 不为空）
                query = query.eq('status', 1)
                query = query.not_().is_('activated_at', 'null')
                query = query.not_().in_('sale_status', ['refunded', 'disputed'])
        
        # 销售状态筛选
        if sale_status:
            query = query.eq('sale_status', sale_status)
        
        response = query.order('id', desc=True).execute()
        cards = response.data or []
        
        # 应用层搜索过滤
        if need_search_filter:
            search_lower = search.lower()
            filtered_cards = []
            for card in cards:
                match_fields = [
                    card.get('key_value', ''),
                    card.get('user_note', ''),
                    card.get('order_id', ''),
                    card.get('link_name', ''),
                    card.get('sales_channel', '')
                ]
                if any(search_lower in str(field).lower() for field in match_fields):
                    filtered_cards.append(card)
            cards = filtered_cards
        
        if not cards:
            return {"success": False, "msg": "没有可导出的数据"}
        
        # 解析导出字段
        if fields:
            export_fields = [f.strip() for f in fields.split(',') if f.strip()]
        else:
            # 默认字段
            export_fields = ['key_value', 'status', 'sale_status', 'expire_at', 'devices', 'bstudio_create_time']
        
        # 字段映射
        field_map = {
            'key_value': ('卡密', lambda c: c.get('key_value', '')),
            'status': ('激活状态', lambda c: '有效' if c.get('status') == 1 else '已停用'),
            'devices': ('绑定设备', lambda c: str(len(json.loads(c.get('devices', '[]'))))),
            'expire_at': ('过期时间', lambda c: format_expire_time(c)),
            'user_note': ('备注', lambda c: c.get('user_note', '')),
            'link_name': ('链接名称', lambda c: c.get('link_name', '')),
            'bstudio_create_time': ('创建时间', lambda c: format_create_time(c.get('bstudio_create_time'))),
            'sale_status': ('销售状态', lambda c: {'unsold': '未售出', 'sold': '已售出', 'refunded': '已退款', 'disputed': '有纠纷'}.get(c.get('sale_status'), c.get('sale_status', '-'))),
            'sales_channel': ('销售渠道', lambda c: c.get('sales_channel', '')),
            'order_id': ('订单号', lambda c: c.get('order_id', '')),
            'feishu_password': ('访问密码', lambda c: c.get('feishu_password', '')),
            'feishu_url': ('飞书链接', lambda c: c.get('feishu_url', '')),
            'max_devices': ('最大设备数', lambda c: c.get('max_devices', 5)),
            'last_used_at': ('最后使用时间', lambda c: format_create_time(c.get('last_used_at'))),
        }
        
        def format_expire_time(card):
            if card.get('expire_at'):
                expire_at_str = str(card['expire_at'])
                return expire_at_str.split('T')[0] if 'T' in expire_at_str else expire_at_str
            elif card.get('expire_after_days'):
                return f"激活后{card['expire_after_days']}天"
            else:
                return "永久"
        
        def format_create_time(time_str):
            if not time_str:
                return '-'
            time_str = str(time_str)
            return time_str.replace('T', ' ').split('.')[0] if 'T' in time_str else time_str
        
        # 筛选有效字段
        valid_fields = [(f, field_map[f]) for f in export_fields if f in field_map]
        if not valid_fields:
            valid_fields = [('key_value', field_map['key_value'])]
        
        # 根据格式生成文件
        import io
        
        if format == 'xlsx':
            from openpyxl import Workbook
            wb = Workbook()
            ws = wb.active
            ws.title = "卡密列表"
            
            # 表头
            headers = [f[1][0] for f in valid_fields]
            ws.append(headers)
            
            # 数据行
            for card in cards:
                row = [f[1][1](card) for f in valid_fields]
                ws.append(row)
            
            output = io.BytesIO()
            wb.save(output)
            output.seek(0)
            
            from fastapi.responses import StreamingResponse
            # 使用英文文件名避免编码问题
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"card_type_{type_id}_export_{timestamp}.xlsx"
            
            return StreamingResponse(
                output,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )
        else:
            # CSV 或 TXT
            import csv
            output = io.StringIO()
            
            if format == 'csv':
                # CSV 带 BOM 头，兼容 Excel
                output.write('\ufeff')
            
            writer = csv.writer(output, lineterminator='\n')
            
            # 表头
            headers = [f[1][0] for f in valid_fields]
            writer.writerow(headers)
            
            # 数据行
            for card in cards:
                row = [f[1][1](card) for f in valid_fields]
                writer.writerow(row)
            
            output.seek(0)
            
            from fastapi.responses import StreamingResponse
            ext = 'csv' if format == 'csv' else 'txt'
            media_type = 'text/csv' if format == 'csv' else 'text/plain'
            # 使用英文文件名避免编码问题
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"card_type_{type_id}_export_{timestamp}.{ext}"
            
            return StreamingResponse(
                io.BytesIO(output.getvalue().encode('utf-8')),
                media_type=media_type,
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )
        
    except Exception as e:
        logger.error(f"导出卡密失败: {str(e)}")
        return {"success": False, "msg": str(e)}


class BatchDeleteRequest(BaseModel):
    """批量删除请求"""
    ids: List[int]


@app.post("/api/admin/cards/batch-delete")
async def batch_delete_cards(request: BatchDeleteRequest):
    """批量删除卡密"""
    try:
        client = get_supabase_client()
        
        if not request.ids or len(request.ids) == 0:
            return {"success": False, "msg": "请选择要删除的卡密"}
        
        # 先删除相关的访问日志
        try:
            client.table('access_logs').delete().in_('card_key_id', request.ids).execute()
        except Exception as e:
            logger.warning(f"删除关联日志失败（不影响主操作）: {str(e)}")
        
        # 删除卡密
        response = client.table('card_keys_table').delete().in_('id', request.ids).execute()
        deleted_count = len(response.data) if response.data else len(request.ids)
        
        # 记录操作日志
        safe_log_operation(client, {
            "operator": "admin",
            "operation_type": "batch_delete",
            "filter_conditions": {"ids": request.ids},
            "affected_count": deleted_count,
            "affected_ids": request.ids[:100],
            "update_fields": {},
            "remark": f"批量删除 {deleted_count} 张卡密"
        })
        
        return {
            "success": True,
            "data": {"deleted_count": deleted_count},
            "msg": f"成功删除 {deleted_count} 张卡密"
        }
        
    except Exception as e:
        logger.error(f"批量删除失败: {str(e)}")
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
                    # 有效：status=1 且 从未激活过（activated_at 为空）
                    query = query.eq('status', 1)
                    query = query.is_('activated_at', 'null')
                    query = query.not_().in_('sale_status', ['refunded', 'disputed'])
                elif activate_status == 'activated':
                    # 已激活：曾经绑定过设备（activated_at 不为空）
                    query = query.eq('status', 1)
                    query = query.not_().is_('activated_at', 'null')
                    query = query.not_().in_('sale_status', ['refunded', 'disputed'])
            
            if filters.get('sale_status') and filters.get('sale_status') != '':
                sale_status_value = filters['sale_status']
                if sale_status_value == '__none__':
                    # 特殊值：筛选未设置销售状态的记录
                    query = query.or_('sale_status.is.null,sale_status.eq.')
                else:
                    # 映射中文值到英文
                    sale_status_map = {
                        '未销售': 'unsold',
                        '已售出': 'sold',
                        '已退款': 'refunded',
                        '有纠纷': 'disputed'
                    }
                    mapped_status = sale_status_map.get(sale_status_value, sale_status_value)
                    query = query.eq('sale_status', mapped_status)
            
            if filters.get('feishu_url') and filters.get('feishu_url') != '':
                query = query.eq('feishu_url', filters['feishu_url'])
            
            # 销售渠道筛选
            if filters.get('sales_channel') and filters.get('sales_channel') != '':
                if filters['sales_channel'] == '未设置':
                    # 特殊值：筛选未设置销售渠道的记录
                    query = query.or_('sales_channel.is.null,sales_channel.eq.')
                else:
                    query = query.eq('sales_channel', filters['sales_channel'])
            
            # 绑定设备筛选（按设备数量）
            device_filter = filters.get('device_filter')
            need_device_filter = False
            device_count_filter = 0
            if device_filter and device_filter != '':
                if device_filter == '0':
                    # 未绑定：设备列表为空
                    query = query.eq('devices', '[]')
                elif device_filter == '1+':
                    # 已绑定：设备列表不为空（需要在应用层过滤）
                    need_device_filter = True
                    device_count_filter = -1  # -1 表示筛选大于0的记录
                else:
                    # 兼容旧版数字筛选
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
            need_expire_filter = False  # 是否需要在应用层过滤过期状态
            if expire_days and expire_days != '':
                now = get_beijing_time()
                if expire_days == 'expired':
                    # 已过期：需要在应用层过滤（包括固定日期过期和激活后N天过期）
                    need_expire_filter = True
                    # 查询所有可能过期的记录（有 expire_at 或 expire_after_days）
                    query = query.or_('expire_at.not.is.null,expire_after_days.not.is.null')
                elif expire_days == 'permanent':
                    query = query.is_('expire_at', 'null').is_('expire_after_days', 'null')
                elif expire_days.startswith('date:'):
                    # 按具体日期筛选
                    target_date = expire_days[5:]
                    start_time = f"{target_date}T00:00:00"
                    end_time = f"{target_date}T23:59:59"
                    query = query.not_().is_('expire_at', 'null').gte('expire_at', start_time).lte('expire_at', end_time)
                elif expire_days.startswith('relative:'):
                    # 激活后N天有效
                    days = int(expire_days[9:])
                    query = query.eq('expire_after_days', days)
                else:
                    try:
                        days = int(expire_days)
                        future_date = (now + timedelta(days=days)).isoformat()
                        query = query.not_().is_('expire_at', 'null').gte('expire_at', now.isoformat()).lte('expire_at', future_date)
                    except ValueError:
                        pass
            
            # 搜索 - 改为应用层过滤
            need_search_filter = False
            search_keyword = ''
            if filters.get('search') and filters.get('search') != '':
                search_keyword = filters['search'].strip()
                need_search_filter = True
            
            if filters.get('created_start') and filters.get('created_start') != '':
                query = query.gte('bstudio_create_time', filters['created_start'])
            if filters.get('created_end') and filters.get('created_end') != '':
                query = query.lte('bstudio_create_time', filters['created_end'] + 'T23:59:59')
            
            # 获取符合条件的记录
            response = query.execute()
            
            # 如果需要在应用层过滤设备数量、过期状态或搜索
            if need_device_filter or need_expire_filter or need_search_filter:
                filtered_data = []
                for card in response.data:
                    # 设备数量过滤
                    if need_device_filter:
                        try:
                            devices = json.loads(card.get('devices', '[]'))
                            device_len = len(devices)
                            if device_count_filter == -1:
                                # -1 表示已绑定（设备数 > 0）
                                if device_len == 0:
                                    continue
                            elif device_len != device_count_filter:
                                continue
                        except:
                            continue
                    
                    # 过期状态过滤
                    if need_expire_filter:
                        # 使用统一的过期判断函数
                        if not calculate_is_expired(card):
                            continue
                    
                    # 搜索过滤
                    if need_search_filter:
                        search_lower = search_keyword.lower()
                        match_fields = [
                            card.get('key_value', ''),
                            card.get('user_note', ''),
                            card.get('order_id', ''),
                            card.get('link_name', ''),
                            card.get('sales_channel', '')
                        ]
                        if not any(search_lower in str(field).lower() for field in match_fields):
                            continue
                    
                    filtered_data.append(card)
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
                update_data['sold_at'] = beijing_time_iso()
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
        
        if 'expire_after_days' in updates:
            update_data['expire_after_days'] = updates['expire_after_days'] or None
        
        if 'user_note' in updates:
            update_data['user_note'] = updates['user_note'] or ''
        
        if 'sales_channel' in updates:
            update_data['sales_channel'] = updates['sales_channel'] or ''
        
        if 'max_devices' in updates and updates['max_devices'] is not None:
            update_data['max_devices'] = int(updates['max_devices'])
        
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
        
        # 处理搜索参数（去除前后空格）
        if search:
            search = search.strip()
        
        # 如果需要设备数量筛选，需要选择devices字段
        need_device_filter = False
        device_count_filter = 0
        if device_filter and device_filter != '':
            if device_filter == '0':
                # 未绑定
                device_count_filter = 0
            elif device_filter == '1+':
                # 已绑定
                need_device_filter = True
                device_count_filter = -1  # -1 表示筛选大于0的记录
            else:
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
                # 有效：status=1 且 从未激活过（activated_at 为空）
                query = query.eq('status', 1)
                query = query.is_('activated_at', 'null')
                query = query.not_().in_('sale_status', ['refunded', 'disputed'])
            elif activate_status == 'activated':
                # 已激活：曾经绑定过设备（activated_at 不为空）
                query = query.eq('status', 1)
                query = query.not_().is_('activated_at', 'null')
                query = query.not_().in_('sale_status', ['refunded', 'disputed'])
        
        if sale_status and sale_status != '':
            if sale_status == '__none__':
                # 特殊值：筛选未设置销售状态的记录
                query = query.or_('sale_status.is.null,sale_status.eq.')
            else:
                # 映射中文值到英文
                sale_status_map = {
                    '未销售': 'unsold',
                    '已售出': 'sold',
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
            if device_filter == '0':
                query = query.eq('devices', '[]')
            elif device_filter == '1+':
                # 已绑定需要在应用层过滤
                pass
            else:
                try:
                    device_count_filter = int(device_filter)
                    if device_count_filter == 0:
                        query = query.eq('devices', '[]')
                    # else: need_device_filter已经在前面设为True
                except ValueError:
                    pass
        
        # 过期时间筛选
        need_expire_filter = False  # 是否需要在应用层过滤过期状态
        if expire_days and expire_days != '':
            now = datetime.now()
            if expire_days == 'expired':
                # 已过期：需要在应用层过滤（包括固定日期过期和激活后N天过期）
                need_expire_filter = True
                # 查询所有可能过期的记录（有 expire_at 或 expire_after_days）
                query = query.or_('expire_at.not.is.null,expire_after_days.not.is.null')
            elif expire_days == 'permanent':
                query = query.is_('expire_at', 'null').is_('expire_after_days', 'null')
            elif expire_days.startswith('date:'):
                # 按具体日期筛选
                target_date = expire_days[5:]
                start_time = f"{target_date}T00:00:00"
                end_time = f"{target_date}T23:59:59"
                query = query.not_().is_('expire_at', 'null').gte('expire_at', start_time).lte('expire_at', end_time)
            elif expire_days.startswith('relative:'):
                # 激活后N天有效
                days = int(expire_days[9:])
                query = query.eq('expire_after_days', days)
            else:
                try:
                    days = int(expire_days)
                    future_date = (now + timedelta(days=days)).isoformat()
                    query = query.not_().is_('expire_at', 'null').gte('expire_at', now.isoformat()).lte('expire_at', future_date)
                except ValueError:
                    pass
        
        # 搜索 - 改为应用层过滤
        need_search_filter = False
        search_keyword = ''
        if search and search != '':
            search_keyword = search.strip()
            need_search_filter = True
        
        if created_start and created_start != '':
            query = query.gte('bstudio_create_time', created_start)
        if created_end and created_end != '':
            query = query.lte('bstudio_create_time', created_end + 'T23:59:59')
        
        # 如果需要在应用层过滤设备数量、过期状态或搜索
        if need_device_filter or need_expire_filter or need_search_filter:
            response = query.execute()
            count = 0
            for card in response.data:
                # 设备数量过滤
                if need_device_filter:
                    try:
                        devices = json.loads(card.get('devices', '[]'))
                        device_len = len(devices)
                        if device_count_filter == -1:
                            # -1 表示已绑定（设备数 > 0）
                            if device_len == 0:
                                continue
                        elif device_len != device_count_filter:
                            continue
                    except:
                        continue
                
                # 过期状态过滤
                if need_expire_filter:
                    # 使用统一的过期判断函数
                    if not calculate_is_expired(card):
                        continue
                
                # 搜索过滤
                if need_search_filter:
                    search_lower = search_keyword.lower()
                    match_fields = [
                        card.get('key_value', ''),
                        card.get('user_note', ''),
                        card.get('order_id', ''),
                        card.get('link_name', ''),
                        card.get('sales_channel', '')
                    ]
                    if not any(search_lower in str(field).lower() for field in match_fields):
                        continue
                
                count += 1
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
        
        # 处理搜索参数（去除前后空格）
        if search:
            search = search.strip()
        
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
            # 格式化时间字段
            for time_field in ['operation_time', 'created_at']:
                if item.get(time_field):
                    val = item[time_field]
                    # 如果是 datetime 对象，转为字符串
                    if hasattr(val, 'isoformat'):
                        item[time_field] = val.isoformat()
                    # 如果是字符串，保持不变
                    # 统一格式化显示
                    if isinstance(item[time_field], str):
                        item[time_field] = item[time_field].replace('T', ' ').split('+')[0].split('.')[0]
            
            # 兼容旧字段：如果 operation_time 存在，用它覆盖 created_at 显示
            if item.get('operation_time'):
                item['created_at'] = item['operation_time']
            
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
        
        # 格式化时间字段（处理 datetime 对象或字符串）
        for time_field in ['operation_time', 'created_at']:
            if log.get(time_field):
                val = log[time_field]
                if hasattr(val, 'isoformat'):
                    log[time_field] = val.isoformat()
                if isinstance(log[time_field], str):
                    log[time_field] = log[time_field].replace('T', ' ').split('+')[0].split('.')[0]
        
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
    card_type_id: Optional[int] = None,
    exclude_field: Optional[str] = None
):
    """
    获取基于当前筛选条件的各字段可选值 - 优化版：合并多次查询
    
    性能优化：
    - 原来：每个字段单独查询一次（共7次数据库查询）
    - 现在：一次查询获取所有数据，在内存中计算各字段统计
    """
    try:
        client = get_supabase_client()
        
        # 处理搜索参数（去除前后空格）
        if search:
            search = search.strip()
        
        # 【优化】一次查询获取所有需要的数据
        # 包含所有筛选选项需要的字段
        all_response = client.table('card_keys_table').select(
            'status, sale_status, feishu_url, link_name, devices, expire_at, expire_after_days, sales_channel, activated_at, card_type_id, bstudio_create_time'
        ).execute()
        
        all_data = all_response.data or []
        
        # 定义筛选条件判断函数（在内存中判断记录是否满足条件）
        def matches_filter(item: dict, exclude: str = None) -> bool:
            """判断记录是否满足当前筛选条件（可排除指定字段）"""
            # 状态筛选
            if status is not None and status != '' and exclude != 'status':
                item_status = item.get('status', 1)
                devices = item.get('devices', '[]')
                item_sale_status = item.get('sale_status')
                
                if status == 'valid':
                    if item_status != 1 or devices != '[]':
                        return False
                elif status == 'activated':
                    if item_status != 1 or devices == '[]':
                        return False
                elif status == 'disabled':
                    if item_status != 0 and item_sale_status not in ['refunded', 'disputed']:
                        return False
                else:
                    try:
                        if item_status != int(status):
                            return False
                    except ValueError:
                        pass
            
            # 销售状态筛选
            if sale_status and sale_status != '' and exclude != 'sale_status':
                item_sale_status = item.get('sale_status') or ''
                if sale_status == '__none__':
                    if item_sale_status not in ['', None]:
                        return False
                elif item_sale_status != sale_status:
                    return False
            
            # 飞书链接筛选
            if feishu_url and feishu_url != '' and exclude != 'feishu_url':
                item_feishu_url = item.get('feishu_url') or ''
                if feishu_url == '__none__':
                    if item_feishu_url != '':
                        return False
                elif item_feishu_url != feishu_url:
                    return False
            
            # 创建时间筛选
            if created_start and created_start != '' and exclude != 'created_start':
                create_time = item.get('bstudio_create_time', '')
                if create_time < created_start:
                    return False
            if created_end and created_end != '' and exclude != 'created_end':
                create_time = item.get('bstudio_create_time', '')
                if create_time > created_end + 'T23:59:59':
                    return False
            
            # 设备筛选
            if device_filter and device_filter != '' and exclude != 'device_filter':
                devices = item.get('devices', '[]')
                try:
                    device_list = json.loads(devices) if isinstance(devices, str) else devices
                    device_count = len(device_list)
                except:
                    device_count = 0
                
                if device_filter == '0':
                    if device_count != 0:
                        return False
                elif device_filter == '1+':
                    if device_count == 0:
                        return False
                else:
                    try:
                        if device_count != int(device_filter):
                            return False
                    except ValueError:
                        pass
            
            # 过期时间筛选
            if expire_days and expire_days != '' and exclude != 'expire_days':
                item_expire_at = item.get('expire_at')
                item_expire_after_days = item.get('expire_after_days')
                item_activated_at = item.get('activated_at')
                
                now = datetime.now()
                
                if expire_days == 'expired':
                    # 已过期（需要在内存中判断）
                    is_expired = False
                    if item_expire_at:
                        try:
                            expire_time = datetime.fromisoformat(str(item_expire_at).replace('Z', '+00:00'))
                            if expire_time.tzinfo:
                                expire_time = expire_time.replace(tzinfo=None)
                            if expire_time < now:
                                is_expired = True
                        except:
                            pass
                    elif item_expire_after_days and item_activated_at:
                        try:
                            activated_time = datetime.fromisoformat(str(item_activated_at).replace('Z', '+00:00'))
                            if activated_time.tzinfo:
                                activated_time = activated_time.replace(tzinfo=None)
                            expire_time = activated_time + timedelta(days=item_expire_after_days)
                            if expire_time < now:
                                is_expired = True
                        except:
                            pass
                    if not is_expired:
                        return False
                elif expire_days == 'permanent':
                    if item_expire_at is not None or item_expire_after_days is not None:
                        return False
                elif expire_days.startswith('date:'):
                    target_date = expire_days[5:]
                    if not item_expire_at or not str(item_expire_at).startswith(target_date):
                        return False
                elif expire_days.startswith('relative:'):
                    days = int(expire_days[9:])
                    if item_expire_after_days != days:
                        return False
            
            # 销售渠道筛选
            if sales_channel and sales_channel != '' and exclude != 'sales_channel':
                item_channel = item.get('sales_channel') or ''
                if sales_channel == '未设置':
                    if item_channel != '':
                        return False
                elif item_channel != sales_channel:
                    return False
            
            # 卡种筛选
            if card_type_id is not None and exclude != 'card_type_id':
                if item.get('card_type_id') != card_type_id:
                    return False
            
            return True
        
        # 初始化统计容器
        status_count = {}
        sale_status_count = {}
        feishu_url_groups = {}
        sales_channel_count = {}
        expire_groups = {}
        relative_groups = {}
        permanent_count = 0
        expired_count = 0
        card_type_count = {}
        no_card_type_count = 0
        
        now = datetime.now()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # 遍历所有数据，分别计算各字段的统计（排除对应字段的筛选条件）
        for item in all_data:
            # 1. 状态统计（排除 status 筛选）
            if matches_filter(item, exclude='status'):
                s = item.get('status')
                key = str(s) if s is not None else '0'
                status_count[key] = status_count.get(key, 0) + 1
            
            # 2. 销售状态统计（排除 sale_status 筛选）
            if matches_filter(item, exclude='sale_status'):
                s = item.get('sale_status') or '__none__'
                sale_status_count[s] = sale_status_count.get(s, 0) + 1
            
            # 3. 飞书链接统计（排除 feishu_url 筛选）
            if matches_filter(item, exclude='feishu_url'):
                url = item.get('feishu_url') or ''
                name = item.get('link_name') or ''
                url_key = url.strip() if url.strip() else ''
                if url_key not in feishu_url_groups:
                    feishu_url_groups[url_key] = {"url": url_key, "count": 0, "names": []}
                feishu_url_groups[url_key]["count"] += 1
                if name and name not in feishu_url_groups[url_key]["names"]:
                    feishu_url_groups[url_key]["names"].append(name)
            
            # 4. 销售渠道统计（排除 sales_channel 筛选）
            if matches_filter(item, exclude='sales_channel'):
                channel = item.get('sales_channel') or '未设置'
                sales_channel_count[channel] = sales_channel_count.get(channel, 0) + 1
            
            # 5. 过期时间统计（排除 expire_days 筛选）
            if matches_filter(item, exclude='expire_days'):
                item_expire_at = item.get('expire_at')
                item_expire_after_days = item.get('expire_after_days')
                item_activated_at = item.get('activated_at')
                
                # 优先处理激活后N天有效
                if item_expire_after_days is not None:
                    days = item_expire_after_days
                    
                    # 检查是否已过期
                    if item_activated_at:
                        try:
                            if isinstance(item_activated_at, str):
                                activated_time = datetime.fromisoformat(item_activated_at.replace('Z', '+00:00'))
                                if activated_time.tzinfo:
                                    activated_time = activated_time.replace(tzinfo=None)
                            else:
                                activated_time = item_activated_at
                                if activated_time.tzinfo is not None:
                                    activated_time = activated_time.replace(tzinfo=None)
                            
                            expire_time = activated_time + timedelta(days=days)
                            if expire_time < now:
                                expired_count += 1
                            else:
                                relative_groups[days] = relative_groups.get(days, 0) + 1
                        except:
                            relative_groups[days] = relative_groups.get(days, 0) + 1
                    else:
                        relative_groups[days] = relative_groups.get(days, 0) + 1
                elif item_expire_at is None:
                    permanent_count += 1
                else:
                    try:
                        if isinstance(item_expire_at, str):
                            expire_date = datetime.fromisoformat(item_expire_at.replace('Z', '+00:00'))
                            expire_date = expire_date.replace(tzinfo=None)
                        else:
                            expire_date = item_expire_at
                            if expire_date.tzinfo is not None:
                                expire_date = expire_date.replace(tzinfo=None)
                        expire_date_only = expire_date.replace(hour=0, minute=0, second=0, microsecond=0)
                        date_key = expire_date_only.strftime('%Y-%m-%d')
                        
                        if expire_date_only < today:
                            expired_count += 1
                        else:
                            expire_groups[date_key] = expire_groups.get(date_key, 0) + 1
                    except:
                        pass
            
            # 6. 卡种统计（排除 card_type_id 筛选）
            if matches_filter(item, exclude='card_type_id'):
                ct_id = item.get('card_type_id')
                if ct_id:
                    card_type_count[ct_id] = card_type_count.get(ct_id, 0) + 1
                else:
                    no_card_type_count += 1
        
        # 构建飞书链接列表
        feishu_url_list = []
        for url_key, data in feishu_url_groups.items():
            if url_key:
                display_name = data["names"][0] if data["names"] else (url_key[:30] + "..." if len(url_key) > 30 else url_key)
                feishu_url_list.append({"url": url_key, "name": display_name, "count": data["count"]})
            else:
                feishu_url_list.append({"url": "__none__", "name": "未设置", "count": data["count"]})
        feishu_url_list.sort(key=lambda x: x['count'], reverse=True)
        
        # 构建销售渠道列表
        sales_channel_list = [{"channel": k, "count": v} for k, v in sales_channel_count.items()]
        sales_channel_list.sort(key=lambda x: x['count'], reverse=True)
        
        # 构建过期时间分组列表
        expire_groups_list = []
        expire_groups_list.append({"value": "expired", "label": "已过期", "count": expired_count})
        for days in sorted(relative_groups.keys()):
            expire_groups_list.append({"value": f"relative:{days}", "label": f"激活后{days}天有效", "count": relative_groups[days]})
        for date_key in sorted(expire_groups.keys()):
            expire_groups_list.append({"value": f"date:{date_key}", "label": f"{date_key} 到期", "count": expire_groups[date_key]})
        expire_groups_list.append({"value": "permanent", "label": "永久有效", "count": permanent_count})
        
        # 获取卡种名称映射
        card_types_response = client.table('card_types').select('id, name').is_('deleted_at', 'null').execute()
        card_types_map = {ct['id']: ct['name'] for ct in card_types_response.data}
        
        # 构建卡种列表
        card_type_list = []
        for ct_id, ct_name in card_types_map.items():
            card_type_list.append({
                "id": ct_id,
                "name": ct_name,
                "count": card_type_count.get(ct_id, 0)
            })
        card_type_list.sort(key=lambda x: x['count'], reverse=True)
        
        if no_card_type_count > 0:
            card_type_list.append({
                "id": None,
                "name": "未分配卡种",
                "count": no_card_type_count
            })
        
        return {
            "success": True,
            "data": {
                "status": status_count,
                "sale_status": sale_status_count,
                "feishu_url_list": feishu_url_list,
                "sales_channel_list": sales_channel_list,
                "expire_groups_list": expire_groups_list,
                "card_type_list": card_type_list,
                "total": len(all_data)
            }
        }
        
    except Exception as e:
        import traceback
        logger.error(f"获取筛选选项失败: {str(e)}")
        logger.error(f"详细堆栈: {traceback.format_exc()}")
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
    - expired: 已过期数量（实时计算）
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
        
        # 已激活：status=1 且有设备绑定
        # 由于需要检查 devices，这需要在应用层处理
        # 先获取所有 status=1 的记录
        activated = 0
        expired = 0  # 已过期数量
        try:
            # 获取 status=1 的记录（包含过期判断所需字段）
            valid_response = client.table('card_keys_table').select('devices, sale_status, expire_at, expire_after_days, activated_at').eq('status', 1).execute()
            for card in (valid_response.data or []):
                # 排除销售状态为退款/纠纷的
                if card.get('sale_status') in ['refunded', 'disputed']:
                    continue
                
                # 检查是否已过期
                if calculate_is_expired(card):
                    expired += 1
                    continue  # 已过期的不计入已激活
                
                # 检查是否已激活（曾经绑定过设备，activated_at 不为空）
                # 这符合业务逻辑：一旦激活过，状态就应该保持，除非卡密到期或手动停用
                if card.get('activated_at'):
                    activated += 1
                # else: 库存（从未激活过），不需要单独计数
        except Exception as e:
            logger.warning(f"计算已激活/已过期数量失败: {str(e)}")
        
        return {
            "success": True,
            "data": {
                "total": total,
                "sold": sold,
                "activated": activated,
                "disabled": disabled,
                "expired": expired
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
    - 按过期日期分组统计（expire_at）
    - 激活后N天有效分组统计（expire_after_days）
    - 永久有效单独分组
    返回：日期、数量、是否已过期
    """
    try:
        client = get_supabase_client()
        
        # 获取所有记录的过期时间、激活后有效天数、激活时间
        response = client.table('card_keys_table').select('expire_at,expire_after_days,activated_at', count='exact').execute()
        
        # 使用日期比较（不含时分秒）
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        now = datetime.now()
        
        # 统计每个过期日期的数量
        permanent_count = 0  # 永久有效（expire_at和expire_after_days都为None）
        expired_count = 0    # 已过期（过期日期小于今天，或激活后N天已过期）
        expire_groups = {}   # 未过期的具体日期（过期日期>=今天）
        relative_groups = {} # 激活后N天有效（expire_after_days），未过期
        
        for item in response.data:
            expire_at = item.get('expire_at')
            expire_after_days = item.get('expire_after_days')
            activated_at = item.get('activated_at')
            
            # 优先处理激活后N天有效
            if expire_after_days is not None:
                # 激活后N天有效
                days = expire_after_days
                
                # 检查是否已过期（需要已激活才能判断）
                if activated_at:
                    try:
                        if isinstance(activated_at, str):
                            activated_time = datetime.fromisoformat(activated_at.replace('Z', '+00:00'))
                            if activated_time.tzinfo:
                                activated_time = activated_time.replace(tzinfo=None)
                        else:
                            activated_time = activated_at
                            if activated_time.tzinfo is not None:
                                activated_time = activated_time.replace(tzinfo=None)
                        
                        # 计算过期时间
                        expire_time = activated_time + timedelta(days=days)
                        if expire_time < now:
                            # 已过期
                            expired_count += 1
                        else:
                            # 未过期，按天数分组
                            if days not in relative_groups:
                                relative_groups[days] = 0
                            relative_groups[days] += 1
                    except Exception as e:
                        logger.warning(f"解析激活时间失败: {activated_at}, {str(e)}")
                        # 解析失败，仍按天数分组显示
                        if days not in relative_groups:
                            relative_groups[days] = 0
                        relative_groups[days] += 1
                else:
                    # 未激活，按天数分组显示
                    if days not in relative_groups:
                        relative_groups[days] = 0
                    relative_groups[days] += 1
            elif expire_at is None:
                # 永久有效：创建卡密时没有填写过期时间，也没有设置激活后有效天数
                permanent_count += 1
            else:
                # 解析过期时间
                try:
                    if isinstance(expire_at, str):
                        # 解析带时区的时间字符串
                        expire_date = datetime.fromisoformat(expire_at.replace('Z', '+00:00'))
                        # 转换为不带时区的本地时间进行比较
                        expire_date = expire_date.replace(tzinfo=None)
                    else:
                        expire_date = expire_at
                        if expire_date.tzinfo is not None:
                            expire_date = expire_date.replace(tzinfo=None)
                    
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
        
        # 激活后N天有效排序（按天数）
        sorted_relative = sorted(relative_groups.items(), key=lambda x: x[0])
        
        # 构建返回结果
        result = []
        
        # 1. 已过期（始终显示）
        result.append({
            'type': 'expired',
            'value': 'expired',
            'label': '已过期',
            'count': expired_count,
            'is_expired': True
        })
        
        # 2. 激活后N天有效
        for days, count in sorted_relative:
            result.append({
                'type': 'relative',
                'value': f"relative:{days}",
                'days': days,
                'label': f"激活后{days}天有效",
                'count': count,
                'is_expired': False
            })
        
        # 3. 未过期的具体日期（按日期排序）
        for group in groups:
            expire_date = datetime.strptime(group['date'], '%Y-%m-%d')
            # 计算距离过期的天数（用日期比较）
            days_remaining = (expire_date - today).days
            label = f"{group['date']} ({days_remaining}天后到期)"
            
            result.append({
                'type': 'date',
                'value': f"date:{group['date']}",
                'date': group['date'],
                'label': label,
                'count': group['count'],
                'days_remaining': days_remaining,
                'is_expired': False
            })
        
        # 4. 永久有效（始终显示）
        result.append({
            'type': 'permanent',
            'value': 'permanent',
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
            'card_type_id': {'db_field': 'card_type_id', 'label': '卡种ID'},
            'devices': {'db_field': 'devices', 'label': '绑定设备'},
            'expire_at': {'db_field': 'expire_at', 'label': '过期时间'},
            'expire_after_days': {'db_field': 'expire_after_days', 'label': '有效天数'},
            'activated_at': {'db_field': 'activated_at', 'label': '激活时间'},
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
        status_map = {1: '有效', 0: '已停用'}
        sale_status_map = {
            'unsold': '未售出', 
            'sold': '已售出', 
            'refunded': '已退款', 
            'disputed': '有纠纷'
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
                    update_data['sold_at'] = beijing_time_iso()
                
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
                    update_data['sold_at'] = beijing_time_iso()
                
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
            '卡密值', '激活状态', '卡种ID', '过期时间', '有效天数', '备注', '链接名称',
            '销售状态', '销售渠道', '订单号', 
            '访问密码', '飞书链接', '最大设备数'
        ]
        writer.writerow(headers)
        
        # 示例数据行1
        writer.writerow([
            'CSS-XXXX-XXXX-XXXX',  # 卡密值（必填）
            '有效',  # 激活状态：有效/已停用
            '1',  # 卡种ID（可选）
            '2026-12-31 23:59:59',  # 过期时间
            '',  # 有效天数（激活后有效天数，与过期时间二选一）
            '测试备注',  # 备注
            '春招信息表',  # 链接名称
            '未售出',  # 销售状态：未售出/已售出/已退款/有纠纷
            '小红书',  # 销售渠道
            'ORDER123456',  # 订单号
            'pwd123',  # 访问密码
            'https://my.feishu.cn/base/xxx',  # 飞书链接
            '5'  # 最大设备数
        ])
        
        # 示例数据行2（使用有效天数过期）
        writer.writerow([
            'CSS-YYYY-YYYY-YYYY',
            '有效',
            '2',
            '',
            '30',  # 激活后30天过期
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
    - 激活状态：有效/已停用（有效=启用，已停用=停用；"已激活"由系统自动判断，不可导入）
    - 销售状态：未售出/已售出/已退款/有纠纷
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
            '备注': 'user_note',
            '卡种ID': 'card_type_id',
            '卡种': 'card_type_id',
            '有效天数': 'expire_after_days'
        }
        
        # 状态映射
        status_map = {
            '有效': 1, '无效': 0, '已停用': 0,
            '1': 1, '0': 0
        }
        
        sale_status_map = {
            '未售出': 'unsold',
            '已售出': 'sold',
            '已销售': 'sold',
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
                                update_data['sold_at'] = beijing_time_iso()
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
                        'bstudio_create_time': beijing_time_iso(),
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
        
        # 同步主键序列（防止序列不同步导致的主键冲突）
        try:
            from storage.database.postgres_client import get_postgres_client
            pg_client = get_postgres_client()
            pg_client.sync_sequence()
            logger.info("主键序列同步完成")
        except Exception as seq_err:
            logger.warning(f"同步主键序列失败（不影响导入结果）: {str(seq_err)}")
        
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
        
        # 添加 is_expired 字段（实时计算）
        card = response.data[0]
        card['is_expired'] = calculate_is_expired(card)
        
        return {"success": True, "data": card}
        
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
        
        # 处理过期时间
        expire_at = None
        expire_after_days = None
        
        # 新版：根据 expire_type 设置
        if card.expire_type == 'fixed' and card.expire_at:
            # 固定日期
            try:
                expire_at = datetime.fromisoformat(card.expire_at.replace('Z', '+00:00')).isoformat()
            except:
                pass
        elif card.expire_type == 'relative' and card.expire_after_days:
            # 激活后N天
            expire_after_days = card.expire_after_days
        elif card.expire_type == 'permanent':
            # 永久有效
            pass
        elif card.expire_days:
            # 旧版兼容：从当前时间计算
            expire_at = (get_beijing_time() + timedelta(days=card.expire_days)).isoformat()
        
        data = {
            "key_value": card.key_value.upper(),
            "card_type_id": card.card_type_id,
            "status": card.status,
            "user_note": card.user_note or "",
            "feishu_url": card.feishu_url or "",
            "feishu_password": card.feishu_password or "",
            "link_name": card.link_name or "",
            "sys_platform": "卡密系统",
            "uuid": str(uuid.uuid4()),
            "bstudio_create_time": beijing_time_iso(),
            "expire_at": expire_at,
            "expire_after_days": expire_after_days,
            "max_uses": card.max_uses,
            "max_devices": card.max_devices,
            "used_count": 0,
            "sale_status": card.sale_status or "unsold",
            "order_id": card.order_id or None,
            "sales_channel": card.sales_channel or ""
        }
        
        response = client.table('card_keys_table').insert(data).execute()
        
        return {"success": True, "data": response.data[0], "msg": "创建成功"}
        
    except Exception as e:
        logger.error(f"创建卡密失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.post("/api/admin/cards/batch-generate")
async def batch_generate_cards(req: BatchGenerateRequest):
    """
    批量生成卡密（兼容旧版API）
    - 生成指定数量的卡密
    - 自动设置过期时间和使用次数限制
    
    新版API请使用 POST /api/admin/card-types/{type_id}/cards/batch-generate
    """
    try:
        if req.count < 1 or req.count > 1000:
            return {"success": False, "msg": "生成数量必须在 1-1000 之间"}
        
        client = get_supabase_client()
        
        # 确定过期方式
        expire_type = req.expire_type
        expire_at = req.expire_at
        expire_after_days = req.expire_after_days
        
        # 兼容旧版：如果没传 expire_type 但有 expire_at，当作固定日期处理
        if not expire_type and expire_at:
            expire_type = 'fixed'
        
        # 如果都没设置，默认永久有效
        if not expire_type:
            expire_type = 'permanent'
        
        # 验证过期方式
        if expire_type == 'fixed' and not expire_at:
            return {"success": False, "msg": "固定日期过期必须指定过期时间"}
        if expire_type == 'relative' and not expire_after_days:
            return {"success": False, "msg": "按激活天数过期必须指定有效天数"}
        
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
            
            card_data = {
                "key_value": key,
                "status": 1,
                "user_note": req.user_note,
                "feishu_url": req.feishu_url,
                "feishu_password": req.feishu_password,
                "link_name": req.link_name,
                "sys_platform": "卡密系统",
                "uuid": str(uuid.uuid4()),
                "bstudio_create_time": beijing_time_iso(),
                "max_devices": 5,
                "used_count": 0,
                "devices": "[]",
                "sales_channel": req.sales_channel,
                "sale_status": "unsold"
            }
            
            # 设置过期方式
            if expire_type == 'fixed':
                card_data["expire_at"] = expire_at
            elif expire_type == 'relative':
                card_data["expire_after_days"] = expire_after_days
            # permanent 类型不设置过期时间
            
            cards.append(card_data)
        
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
        
        # 同步主键序列（防止序列不同步导致的主键冲突）
        try:
            from storage.database.postgres_client import get_postgres_client
            pg_client = get_postgres_client()
            pg_client.sync_sequence()
            logger.info("主键序列同步完成")
        except Exception as seq_err:
            logger.warning(f"同步主键序列失败（不影响生成结果）: {str(seq_err)}")
        
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
        if card.expire_after_days is not None:
            update_data["expire_after_days"] = card.expire_after_days
        if card.max_uses is not None:
            update_data["max_uses"] = card.max_uses
        if card.max_devices is not None:
            update_data["max_devices"] = card.max_devices
        if card.sale_status is not None:
            update_data["sale_status"] = card.sale_status
            # 已售出时记录时间
            if card.sale_status == 'sold':
                update_data["sold_at"] = beijing_time_iso()
        if card.order_id is not None:
            # 空字符串转为 None，用于清空订单号
            update_data["order_id"] = card.order_id if card.order_id else None
        if card.sales_channel is not None:
            update_data["sales_channel"] = card.sales_channel
        
        # 检查是否有实际需要更新的内容
        if not update_data:
            return {"success": True, "msg": "没有需要更新的字段"}
        
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
        
        # 处理搜索参数（去除前后空格）
        if search:
            search = search.strip()
        
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
            cutoff_time = (get_beijing_time() - timedelta(days=days)).isoformat()
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
            # 查找过期卡密的日志（包括固定过期日期和激活后N天过期）
            now = datetime.now()
            # 1. 固定过期日期的卡密
            expired_fixed = client.table('card_keys_table').select('key_value').not_.is_('expire_at', 'null').lt('expire_at', now.isoformat()).execute()
            expired_keys = [card['key_value'] for card in (expired_fixed.data or [])]
            
            # 2. 激活后N天有效且已过期的卡密
            relative_cards = client.table('card_keys_table').select('key_value, expire_after_days, activated_at').not_.is_('expire_after_days', 'null').not_.is_('activated_at', 'null').execute()
            for card in (relative_cards.data or []):
                try:
                    activated_at = card['activated_at']
                    expire_after_days = card['expire_after_days']
                    if isinstance(activated_at, str):
                        activated_time = datetime.fromisoformat(activated_at.replace('Z', '+00:00'))
                    else:
                        activated_time = activated_at
                    if activated_time.tzinfo is not None:
                        activated_time = activated_time.replace(tzinfo=None)
                    expire_time = activated_time + timedelta(days=expire_after_days)
                    if expire_time < now:
                        expired_keys.append(card['key_value'])
                except:
                    pass
            
            if expired_keys:
                query = query.in_('key_value', expired_keys)
            else:
                return {"success": True, "count": 0, "condition": request.condition, "days": request.days}
        
        # 应用时间筛选
        if request.days > 0:
            cutoff_time = (get_beijing_time() - timedelta(days=request.days)).isoformat()
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
            # 查找过期卡密的日志（包括固定过期日期和激活后N天过期）
            now = datetime.now()
            # 1. 固定过期日期的卡密
            expired_fixed = client.table('card_keys_table').select('key_value').not_.is_('expire_at', 'null').lt('expire_at', now.isoformat()).execute()
            expired_keys = [card['key_value'] for card in (expired_fixed.data or [])]
            
            # 2. 激活后N天有效且已过期的卡密
            relative_cards = client.table('card_keys_table').select('key_value, expire_after_days, activated_at').not_.is_('expire_after_days', 'null').not_.is_('activated_at', 'null').execute()
            for card in (relative_cards.data or []):
                try:
                    activated_at = card['activated_at']
                    expire_after_days = card['expire_after_days']
                    if isinstance(activated_at, str):
                        activated_time = datetime.fromisoformat(activated_at.replace('Z', '+00:00'))
                    else:
                        activated_time = activated_at
                    if activated_time.tzinfo is not None:
                        activated_time = activated_time.replace(tzinfo=None)
                    expire_time = activated_time + timedelta(days=expire_after_days)
                    if expire_time < now:
                        expired_keys.append(card['key_value'])
                except:
                    pass
            
            if expired_keys:
                query = query.in_('key_value', expired_keys)
            else:
                # 没有过期卡密，无需清理
                return {"success": True, "msg": "没有符合条件的日志", "deleted_count": 0}
        
        # 应用时间筛选
        if request.days > 0:
            cutoff_time = (get_beijing_time() - timedelta(days=request.days)).isoformat()
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
    current_password = get_admin_password()
    if request.password != current_password:
        logger.warning(f"登录失败: 密码错误")
        return {"success": False, "msg": "密码错误"}
    
    token = create_token()
    logger.info(f"管理员登录成功, token={token[:10]}...")
    
    # 设置 cookie
    # 注意：生产环境 HTTPS 需要设置 secure=True
    response.set_cookie(
        key="admin_token",
        value=token,
        max_age=TOKEN_EXPIRE_HOURS * 3600,
        httponly=True,
        samesite="lax",
        path="/"  # 确保 cookie 在所有路径下都可用
    )
    
    return {"success": True, "token": token}


@app.post("/api/admin/logout")
async def admin_logout(response: JSONResponse):
    """管理员登出"""
    response.delete_cookie("admin_token")
    return {"success": True}


@app.post("/api/admin/change-password")
async def change_password(request: ChangePasswordRequest, req: Request):
    """修改管理员密码"""
    # 验证是否已登录
    token = get_token_from_request(req)
    if not verify_token(token):
        return {"success": False, "msg": "未登录或会话已过期"}
    
    # 验证旧密码
    current_password = get_admin_password()
    if request.old_password != current_password:
        return {"success": False, "msg": "旧密码错误"}
    
    # 验证新密码
    if not request.new_password or len(request.new_password) < 4:
        return {"success": False, "msg": "新密码长度不能少于4位"}
    
    if len(request.new_password) > 50:
        return {"success": False, "msg": "新密码长度不能超过50位"}
    
    # 保存新密码
    if set_admin_password(request.new_password):
        logger.info("管理员密码修改成功")
        return {"success": True, "msg": "密码修改成功"}
    else:
        return {"success": False, "msg": "密码保存失败，请稍后重试"}


# ==================== 系统设置 API ====================

class DocsUrlRequest(BaseModel):
    """文档链接请求"""
    url: str


@app.get("/api/admin/settings/docs-url")
async def get_docs_url(req: Request):
    """获取文档中心链接"""
    token = get_token_from_request(req)
    if not verify_token(token):
        return {"success": False, "msg": "未登录或会话已过期"}
    
    try:
        client = get_supabase_client()
        result = client.table('admin_settings').select('value').eq('key', 'docs_url').execute()
        if result.data and len(result.data) > 0:
            return {"success": True, "data": result.data[0]['value']}
        return {"success": True, "data": ""}
    except Exception as e:
        logger.error(f"获取文档链接失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.post("/api/admin/settings/docs-url")
async def set_docs_url(request: DocsUrlRequest, req: Request):
    """设置文档中心链接"""
    token = get_token_from_request(req)
    if not verify_token(token):
        return {"success": False, "msg": "未登录或会话已过期"}
    
    try:
        client = get_supabase_client()
        url = request.url.strip() if request.url else ""
        
        # 先尝试更新
        result = client.table('admin_settings').update({'value': url}).eq('key', 'docs_url').execute()
        if not result.data:
            # 如果没有更新到，说明记录不存在，尝试插入
            client.table('admin_settings').insert({'key': 'docs_url', 'value': url}).execute()
        
        logger.info(f"文档链接设置成功: {url}")
        return {"success": True, "msg": "保存成功"}
    except Exception as e:
        logger.error(f"设置文档链接失败: {str(e)}")
        return {"success": False, "msg": str(e)}


# ==================== 全局预览图设置 API ====================

class GlobalPreviewRequest(BaseModel):
    """全局预览图请求"""
    preview_image: Optional[str] = None  # 兼容旧接口
    image_id: Optional[int] = None  # 新接口：传递图片ID
    enabled: bool = False


@app.get("/api/admin/settings/global-preview")
async def get_global_preview(req: Request):
    """获取全局预览图设置"""
    token = get_token_from_request(req)
    if not verify_token(token):
        return {"success": False, "msg": "未登录或会话已过期"}
    
    try:
        client = get_supabase_client()
        result = client.table('admin_settings').select('value').eq('key', 'global_preview').execute()
        if result.data and len(result.data) > 0:
            import json
            try:
                data = json.loads(result.data[0]['value'])
                image_key = data.get('image_key', '')
                image_id = data.get('image_id')
                preview_url = data.get('preview_image', '')
                
                # 如果存储的是 key，动态生成 URL
                if image_key and not image_key.startswith('http') and not image_key.startswith('data:'):
                    import os
                    from coze_coding_dev_sdk.s3 import S3SyncStorage
                    
                    storage = S3SyncStorage(
                        endpoint_url=os.getenv("COZE_BUCKET_ENDPOINT_URL"),
                        access_key="",
                        secret_key="",
                        bucket_name=os.getenv("COZE_BUCKET_NAME"),
                        region="cn-beijing",
                    )
                    preview_url = storage.generate_presigned_url(key=image_key, expire_time=86400)
                
                return {"success": True, "data": {
                    "preview_image": preview_url,
                    "image_id": image_id,
                    "enabled": data.get('enabled', False)
                }}
            except:
                return {"success": True, "data": {"preview_image": "", "image_id": None, "enabled": False}}
        return {"success": True, "data": {"preview_image": "", "image_id": None, "enabled": False}}
    except Exception as e:
        logger.error(f"获取全局预览图设置失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.post("/api/admin/settings/global-preview")
async def set_global_preview(request: GlobalPreviewRequest, req: Request):
    """设置全局预览图"""
    token = get_token_from_request(req)
    if not verify_token(token):
        return {"success": False, "msg": "未登录或会话已过期"}
    
    try:
        client = get_supabase_client()
        import json
        import os
        from coze_coding_dev_sdk.s3 import S3SyncStorage
        
        image_key = ''
        image_id = None
        
        # 如果传递了 image_id，从预览图片表中获取 image_key
        if request.image_id:
            img_result = client.table('preview_images').select('*').eq('id', request.image_id).execute()
            if img_result.data:
                img_data = img_result.data[0]
                image_key = img_data.get('image_key') or img_data.get('url', '')
                image_id = request.image_id
        # 兼容旧接口：如果传递了 preview_image
        elif request.preview_image:
            image_key = request.preview_image
        
        value = json.dumps({
            "preview_image": image_key,  # 存储 key 而非 URL
            "image_key": image_key,
            "image_id": image_id,
            "enabled": request.enabled
        })
        
        # 先尝试更新
        result = client.table('admin_settings').update({'value': value}).eq('key', 'global_preview').execute()
        if not result.data:
            # 如果没有更新到，说明记录不存在，尝试插入
            client.table('admin_settings').insert({'key': 'global_preview', 'value': value}).execute()
        
        logger.info(f"全局预览图设置成功, image_id={image_id}, enabled={request.enabled}")
        return {"success": True, "msg": "保存成功"}
    except Exception as e:
        logger.error(f"设置全局预览图失败: {str(e)}")
        return {"success": False, "msg": str(e)}


# ==================== 预览图片管理 API ====================

class PreviewImageRequest(BaseModel):
    """预览图片请求"""
    name: str


@app.get("/api/admin/preview-images")
async def get_preview_images(req: Request):
    """获取预览图片列表"""
    token = get_token_from_request(req)
    if not verify_token(token):
        return {"success": False, "msg": "未登录或会话已过期"}
    
    try:
        client = get_supabase_client()
        result = client.table('preview_images').select('*').order('created_at', desc=True).execute()
        
        # 动态生成 URL
        images = result.data or []
        if images:
            import os
            from coze_coding_dev_sdk.s3 import S3SyncStorage
            
            storage = S3SyncStorage(
                endpoint_url=os.getenv("COZE_BUCKET_ENDPOINT_URL"),
                access_key="",
                secret_key="",
                bucket_name=os.getenv("COZE_BUCKET_NAME"),
                region="cn-beijing",
            )
            
            for img in images:
                image_key = img.get('image_key') or img.get('url')  # 兼容旧数据
                if image_key and not image_key.startswith('data:') and not image_key.startswith('http'):
                    # 存储的是 key，动态生成 URL
                    img['url'] = storage.generate_presigned_url(key=image_key, expire_time=86400)
                elif image_key and image_key.startswith('http'):
                    # 旧数据存储的是 URL，保持不变
                    img['url'] = image_key
                # base64 数据保持不变
        
        return {"success": True, "data": images}
    except Exception as e:
        logger.error(f"获取预览图片列表失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.post("/api/admin/preview-images")
async def upload_preview_image(req: Request, file: UploadFile = File(...), name: str = Form(...)):
    """上传预览图片"""
    token = get_token_from_request(req)
    if not verify_token(token):
        return {"success": False, "msg": "未登录或会话已过期"}
    
    try:
        # 验证文件类型
        if not file.content_type or not file.content_type.startswith('image/'):
            return {"success": False, "msg": "请上传图片文件"}
        
        # 验证文件大小（5MB）
        content = await file.read()
        if len(content) > 5 * 1024 * 1024:
            return {"success": False, "msg": "图片大小不能超过5MB"}
        
        # 验证图片名称
        if not name or not name.strip():
            return {"success": False, "msg": "请输入图片名称"}
        
        name = name.strip()[:100]  # 限制名称长度
        
        client = get_supabase_client()
        
        # 使用 S3SyncStorage 上传图片
        try:
            import os
            from coze_coding_dev_sdk.s3 import S3SyncStorage
            
            storage = S3SyncStorage(
                endpoint_url=os.getenv("COZE_BUCKET_ENDPOINT_URL"),
                access_key="",
                secret_key="",
                bucket_name=os.getenv("COZE_BUCKET_NAME"),
                region="cn-beijing",
            )
            
            # 生成文件名
            file_ext = file.filename.split('.')[-1] if file.filename else 'png'
            file_name = f"preview_images/{datetime.now().strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(4)}.{file_ext}"
            
            # 上传文件，获取实际的 key
            actual_key = storage.upload_file(
                file_content=content,
                file_name=file_name,
                content_type=file.content_type,
            )
            
            # 生成访问URL（有效期1天，用于即时显示）
            image_url = storage.generate_presigned_url(key=actual_key, expire_time=86400)
            
            # 保存到预览图片表 - 存储 key 而非 URL
            result = client.table('preview_images').insert({
                'name': name,
                'image_key': actual_key,
                'url': actual_key  # 兼容旧字段，存储 key
            }).execute()
            
            # 返回数据包含动态生成的 URL
            return_data = {"name": name, "url": image_url, "image_key": actual_key}
            if result.data:
                return_data = {**result.data[0], "url": image_url}
            
            logger.info(f"预览图片上传成功: {name}, key={actual_key}")
            return {"success": True, "data": return_data}
            
        except Exception as storage_err:
            logger.error(f"存储上传失败: {str(storage_err)}")
            return {"success": False, "msg": f"图片上传失败: {str(storage_err)}"}
            
    except Exception as e:
        logger.error(f"上传预览图片失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.delete("/api/admin/preview-images/{image_id}")
async def delete_preview_image(image_id: int, req: Request):
    """删除预览图片"""
    token = get_token_from_request(req)
    if not verify_token(token):
        return {"success": False, "msg": "未登录或会话已过期"}
    
    try:
        client = get_supabase_client()
        
        # 先获取图片信息
        result = client.table('preview_images').select('*').eq('id', image_id).execute()
        if result.data:
            img_data = result.data[0]
            image_key = img_data.get('image_key') or img_data.get('url', '')
            
            # 尝试从存储中删除（如果是对象存储的 key）
            if image_key and not image_key.startswith('data:') and not image_key.startswith('http'):
                try:
                    import os
                    from coze_coding_dev_sdk.s3 import S3SyncStorage
                    
                    storage = S3SyncStorage(
                        endpoint_url=os.getenv("COZE_BUCKET_ENDPOINT_URL"),
                        access_key="",
                        secret_key="",
                        bucket_name=os.getenv("COZE_BUCKET_NAME"),
                        region="cn-beijing",
                    )
                    
                    # 直接使用存储的 key 删除文件
                    storage.delete_file(file_key=image_key)
                    logger.info(f"已从对象存储删除文件: {image_key}")
                except Exception as e:
                    logger.warning(f"从存储删除文件失败: {str(e)}")
            elif image_key and image_key.startswith('http'):
                # 旧数据存储的是 URL，尝试从 URL 中提取 key
                try:
                    import os
                    from coze_coding_dev_sdk.s3 import S3SyncStorage
                    
                    storage = S3SyncStorage(
                        endpoint_url=os.getenv("COZE_BUCKET_ENDPOINT_URL"),
                        access_key="",
                        secret_key="",
                        bucket_name=os.getenv("COZE_BUCKET_NAME"),
                        region="cn-beijing",
                    )
                    
                    # 从 URL 提取 key（URL 格式: endpoint/bucket/key?签名参数）
                    if 'preview_images/' in image_key:
                        key_part = image_key.split('preview_images/')[-1].split('?')[0]
                        file_key = f"preview_images/{key_part}"
                        storage.delete_file(file_key=file_key)
                        logger.info(f"已从对象存储删除文件: {file_key}")
                except Exception as e:
                    logger.warning(f"从存储删除文件失败: {str(e)}")
            
            # 从数据库删除记录
            client.table('preview_images').delete().eq('id', image_id).execute()
            
        logger.info(f"预览图片已删除: {image_id}")
        return {"success": True, "msg": "删除成功"}
    except Exception as e:
        logger.error(f"删除预览图片失败: {str(e)}")
        return {"success": False, "msg": str(e)}


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
            # 解析访问时间（处理 datetime 对象或字符串）
            access_time_raw = log['access_time']
            if hasattr(access_time_raw, 'strftime'):
                # 已经是 datetime 对象
                access_time = access_time_raw
            else:
                # 字符串，需要解析
                access_time = datetime.fromisoformat(str(access_time_raw).replace('Z', '+00:00'))
            
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
        relative_active_count = 0  # 激活后N天有效（未过期）
        permanent_count = 0  # 永久有效（expire_at 和 expire_after_days 都为空）
        
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
            expire_after_days = card.get('expire_after_days')
            activated_at = card.get('activated_at')
            
            # 优先处理激活后N天有效
            if expire_after_days is not None:
                if activated_at:
                    try:
                        if isinstance(activated_at, str):
                            activated_time = datetime.fromisoformat(activated_at.replace('Z', '+00:00'))
                        else:
                            activated_time = activated_at
                        if activated_time.tzinfo is not None:
                            activated_time = activated_time.replace(tzinfo=None)
                        expire_time = activated_time + timedelta(days=expire_after_days)
                        if expire_time < now:
                            expired_count += 1
                        elif expire_time < now + timedelta(days=7):
                            expiring_7days += 1
                        elif expire_time < now + timedelta(days=30):
                            expiring_30days += 1
                        else:
                            relative_active_count += 1
                    except:
                        relative_active_count += 1
                else:
                    # 未激活，不计入过期统计
                    relative_active_count += 1
            elif expire_at:
                try:
                    # 处理字符串或 datetime 对象
                    if isinstance(expire_at, str):
                        expire_time = datetime.fromisoformat(expire_at.replace('Z', '+00:00'))
                    else:
                        expire_time = expire_at
                    # 移除时区信息，避免与 naive datetime 比较时报错
                    if expire_time.tzinfo is not None:
                        expire_time = expire_time.replace(tzinfo=None)
                    if expire_time < now:
                        expired_count += 1
                    elif expire_time < now + timedelta(days=7):
                        expiring_7days += 1
                    elif expire_time < now + timedelta(days=30):
                        expiring_30days += 1
                    # 其他情况：未过期但不在近期内过期，不计入任何统计
                except:
                    pass
            else:
                # expire_at 和 expire_after_days 都为空，表示永久有效
                permanent_count += 1
        
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
                    "relative_active": relative_active_count,
                    "permanent": permanent_count
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
                    # 处理字符串或 datetime 对象
                    if isinstance(expire_at, str):
                        expire_time = datetime.fromisoformat(expire_at.replace('Z', '+00:00'))
                    else:
                        expire_time = expire_at
                    # 移除时区信息，避免与 naive datetime 比较时报错
                    if expire_time.tzinfo is not None:
                        expire_time = expire_time.replace(tzinfo=None)
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
        five_min_ago = (get_beijing_time() - timedelta(minutes=5)).isoformat()
        
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
            "use_real_data": online_count >= 20  # 在线人数>=20时使用真实数据
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
        response = FileResponse(admin_path, media_type="text/html")
        # 禁用缓存，确保用户总是获取最新版本
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
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


# 挂载静态文件目录（禁用缓存）
class NoCacheStaticFiles(StaticFiles):
    """禁用缓存的静态文件服务"""
    async def __call__(self, scope, receive, send) -> None:
        # 先调用父类处理请求
        await super().__call__(scope, receive, send)
    
    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

if os.path.exists(STATIC_DIR):
    app.mount("/static", NoCacheStaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
