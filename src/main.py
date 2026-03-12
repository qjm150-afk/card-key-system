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
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

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
    expire_days: Optional[int] = None  # 有效期天数
    max_uses: int = 1  # 最大使用次数


class CardKeyUpdate(BaseModel):
    """更新卡密"""
    key_value: Optional[str] = None
    status: Optional[int] = None
    user_note: Optional[str] = None
    feishu_url: Optional[str] = None
    feishu_password: Optional[str] = None
    expire_at: Optional[str] = None
    max_uses: Optional[int] = None


class BatchGenerateRequest(BaseModel):
    """批量生成卡密请求"""
    count: int  # 生成数量
    prefix: str = "CSS"  # 卡密前缀
    feishu_url: str = ""  # 飞书链接
    feishu_password: str = ""  # 飞书密码
    expire_days: Optional[int] = None  # 有效期天数
    max_uses: int = 1  # 最大使用次数
    user_note: str = ""  # 备注


class BatchOperation(BaseModel):
    """批量操作"""
    ids: List[int]
    action: str  # delete, activate, deactivate
    feishu_url: Optional[str] = None
    feishu_password: Optional[str] = None


# ==================== Supabase 客户端 ====================

def get_supabase_client():
    """获取 Supabase 客户端"""
    from supabase import create_client, Client, ClientOptions
    import httpx

    url = os.getenv("COZE_SUPABASE_URL")
    anon_key = os.getenv("COZE_SUPABASE_ANON_KEY")

    if not url or not anon_key:
        raise ValueError("COZE_SUPABASE_URL 或 COZE_SUPABASE_ANON_KEY 未设置")

    http_client = httpx.Client(
        timeout=httpx.Timeout(connect=20.0, read=60.0, write=60.0, pool=10.0),
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20, keepalive_expiry=30.0),
        http2=True,
        follow_redirects=True,
    )

    options = ClientOptions(
        httpx_client=http_client,
        auto_refresh_token=False,
    )

    return create_client(url, anon_key, options=options)


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


def get_client_ip(request) -> str:
    """获取客户端IP"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ==================== 验证 API ====================

@app.post("/api/validate", response_model=ValidateResponse)
async def validate_card_key(request: ValidateRequest, fastapi_request: Request):
    """
    验证卡密 API
    - 检查卡密是否存在
    - 检查状态是否有效
    - 检查是否过期
    - 检查使用次数
    - 记录访问日志
    """
    client = None
    card_key = request.card_key.strip().upper()
    ip_address = get_client_ip(fastapi_request)
    user_agent = fastapi_request.headers.get("User-Agent", "")[:500]
    
    try:
        if not card_key:
            return ValidateResponse(can_access=False, msg="请输入卡密")

        logger.info(f"验证卡密: {card_key}, IP: {ip_address}")

        client = get_supabase_client()

        # 查询卡密
        response = client.table('card_keys_table').select('*').eq('key_value', card_key).execute()

        if not response.data:
            # 记录失败日志
            log_access(client, None, card_key, ip_address, user_agent, False, "卡密不存在")
            return ValidateResponse(can_access=False, msg="卡密不存在")

        card_data = response.data[0]
        card_id = card_data.get('id')

        # 检查状态 (1=有效, 0=无效)
        if card_data.get('status') != 1:
            log_access(client, card_id, card_key, ip_address, user_agent, False, "卡密已失效")
            return ValidateResponse(can_access=False, msg="卡密已失效")

        # 检查过期时间
        expire_at = card_data.get('expire_at')
        if expire_at:
            expire_time = datetime.fromisoformat(expire_at.replace('Z', '+00:00'))
            if datetime.now(expire_time.tzinfo) > expire_time:
                log_access(client, card_id, card_key, ip_address, user_agent, False, "卡密已过期")
                return ValidateResponse(can_access=False, msg="卡密已过期")

        # 检查使用次数
        max_uses = card_data.get('max_uses', 1)
        used_count = card_data.get('used_count', 0)
        if used_count >= max_uses:
            log_access(client, card_id, card_key, ip_address, user_agent, False, "卡密使用次数已达上限")
            return ValidateResponse(can_access=False, msg="卡密使用次数已达上限")

        # 验证成功 - 更新使用次数和状态
        new_used_count = used_count + 1
        update_data = {
            "used_count": new_used_count,
            "last_used_at": datetime.now().isoformat()
        }
        
        # 如果达到最大使用次数，自动将状态设为无效
        if new_used_count >= max_uses:
            update_data["status"] = 0
        
        client.table('card_keys_table').update(update_data).eq('id', card_id).execute()

        # 记录成功日志
        log_access(client, card_id, card_key, ip_address, user_agent, True, "验证成功")

        feishu_url = card_data.get('feishu_url', '')
        feishu_password = card_data.get('feishu_password', '')

        logger.info(f"验证成功: {card_key}, URL: {feishu_url}")

        return ValidateResponse(
            can_access=True,
            url=feishu_url,
            password=feishu_password,
            msg="验证成功"
        )

    except Exception as e:
        logger.error(f"验证失败: {str(e)}")
        if client:
            log_access(client, None, card_key, ip_address, user_agent, False, f"系统错误: {str(e)}")
        return ValidateResponse(can_access=False, msg="系统错误，请稍后重试")


def log_access(client, card_key_id, key_value, ip_address, user_agent, success, error_msg):
    """记录访问日志"""
    try:
        client.table('access_logs').insert({
            "card_key_id": card_key_id,
            "key_value": key_value,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "success": success,
            "error_msg": error_msg if not success else None,
            "access_time": datetime.now().isoformat()
        }).execute()
    except Exception as e:
        logger.error(f"记录日志失败: {str(e)}")


# ==================== 管理后台 API ====================

@app.get("/api/admin/cards")
async def get_card_keys(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    status: Optional[int] = None
):
    """获取卡密列表"""
    try:
        client = get_supabase_client()
        
        query = client.table('card_keys_table').select('*', count='exact')
        
        if search:
            query = query.or_(f"key_value.ilike.%{search}%,user_note.ilike.%{search}%")
        
        if status is not None:
            query = query.eq('status', status)
        
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
        
        # 计算过期时间
        expire_at = None
        if req.expire_days:
            expire_at = (datetime.now() + timedelta(days=req.expire_days)).isoformat()
        
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
                "sys_platform": "卡密系统",
                "uuid": str(uuid.uuid4()),
                "bstudio_create_time": datetime.now().isoformat(),
                "expire_at": expire_at,
                "max_uses": req.max_uses,
                "used_count": 0
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
        if card.expire_at is not None:
            update_data["expire_at"] = card.expire_at
        if card.max_uses is not None:
            update_data["max_uses"] = card.max_uses
        
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
    success: Optional[bool] = None
):
    """获取访问日志"""
    try:
        client = get_supabase_client()
        
        query = client.table('access_logs').select('*', count='exact')
        
        if card_key_id:
            query = query.eq('card_key_id', card_key_id)
        if success is not None:
            query = query.eq('success', success)
        
        start = (page - 1) * page_size
        end = start + page_size - 1
        
        response = query.range(start, end).order('access_time', desc=True).execute()
        
        return {
            "success": True,
            "data": response.data,
            "total": response.count,
            "page": page,
            "page_size": page_size
        }
        
    except Exception as e:
        logger.error(f"获取访问日志失败: {str(e)}")
        return {"success": False, "msg": str(e)}


# ==================== 静态文件服务 ====================

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
