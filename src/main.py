"""
卡密验证系统 - 主入口
使用 FastAPI + Supabase 连接 Coze 内置数据库
"""

import os
import sys
import logging
import uuid
from datetime import datetime
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
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
    sys_platform: str = "扣子"


class CardKeyUpdate(BaseModel):
    """更新卡密"""
    key_value: Optional[str] = None
    status: Optional[int] = None
    user_note: Optional[str] = None
    feishu_url: Optional[str] = None
    feishu_password: Optional[str] = None


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


# ==================== API 路由 ====================

@app.post("/api/validate", response_model=ValidateResponse)
async def validate_card_key(request: ValidateRequest):
    """
    验证卡密 API
    从数据库查询卡密信息
    """
    try:
        card_key = request.card_key.strip().upper()
        
        if not card_key:
            return ValidateResponse(
                can_access=False,
                msg="请输入卡密"
            )

        logger.info(f"验证卡密: {card_key}")

        # 获取 Supabase 客户端
        client = get_supabase_client()

        # 查询卡密 (使用资源库数据库表: card_keys_table)
        response = client.table('card_keys_table').select('*').eq('key_value', card_key).execute()

        if not response.data:
            logger.info(f"卡密不存在: {card_key}")
            return ValidateResponse(
                can_access=False,
                msg="卡密不存在"
            )

        card_data = response.data[0]

        # 检查状态 (1=有效, 0=已使用/无效)
        if card_data.get('status') != 1:
            logger.info(f"卡密已失效: {card_key}")
            return ValidateResponse(
                can_access=False,
                msg="卡密已失效"
            )

        # 验证成功
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
        return ValidateResponse(
            can_access=False,
            msg="系统错误，请稍后重试"
        )


# ==================== 管理后台 API ====================

@app.get("/api/admin/cards")
async def get_card_keys(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    status: Optional[int] = None
):
    """
    获取卡密列表
    - page: 页码
    - page_size: 每页数量
    - search: 搜索关键词（卡密/备注）
    - status: 状态筛选（1=有效，0=无效）
    """
    try:
        client = get_supabase_client()
        
        # 构建查询
        query = client.table('card_keys_table').select('*', count='exact')
        
        # 搜索条件
        if search:
            query = query.or_(f"key_value.ilike.%{search}%,user_note.ilike.%{search}%")
        
        # 状态筛选
        if status is not None:
            query = query.eq('status', status)
        
        # 分页
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


@app.post("/api/admin/cards")
async def create_card_key(card: CardKeyCreate):
    """创建卡密"""
    try:
        client = get_supabase_client()
        
        # 检查卡密是否已存在
        existing = client.table('card_keys_table').select('id').eq('key_value', card.key_value.upper()).execute()
        if existing.data:
            return {"success": False, "msg": "卡密已存在"}
        
        # 创建卡密
        data = {
            "key_value": card.key_value.upper(),
            "status": card.status,
            "user_note": card.user_note or "",
            "feishu_url": card.feishu_url or "",
            "feishu_password": card.feishu_password or "",
            "sys_platform": card.sys_platform,
            "uuid": str(uuid.uuid4()),
            "bstudio_create_time": datetime.now().isoformat()
        }
        
        response = client.table('card_keys_table').insert(data).execute()
        
        return {"success": True, "data": response.data[0], "msg": "创建成功"}
        
    except Exception as e:
        logger.error(f"创建卡密失败: {str(e)}")
        return {"success": False, "msg": str(e)}


@app.put("/api/admin/cards/{card_id}")
async def update_card_key(card_id: int, card: CardKeyUpdate):
    """更新卡密"""
    try:
        client = get_supabase_client()
        
        # 构建更新数据
        update_data = {}
        if card.key_value is not None:
            # 检查新卡密是否已存在
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
            # 批量删除
            response = client.table('card_keys_table').delete().in_('id', operation.ids).execute()
            return {"success": True, "msg": f"成功删除 {len(response.data)} 条记录"}
            
        elif operation.action == "activate":
            # 批量激活
            update_data = {"status": 1}
            response = client.table('card_keys_table').update(update_data).in_('id', operation.ids).execute()
            return {"success": True, "msg": f"成功激活 {len(response.data)} 条记录"}
            
        elif operation.action == "deactivate":
            # 批量停用
            update_data = {"status": 0}
            response = client.table('card_keys_table').update(update_data).in_('id', operation.ids).execute()
            return {"success": True, "msg": f"成功停用 {len(response.data)} 条记录"}
            
        elif operation.action == "update_url":
            # 批量更新链接
            if not operation.feishu_url:
                return {"success": False, "msg": "请提供飞书链接"}
            update_data = {
                "feishu_url": operation.feishu_url,
                "feishu_password": operation.feishu_password or ""
            }
            response = client.table('card_keys_table').update(update_data).in_('id', operation.ids).execute()
            return {"success": True, "msg": f"成功更新 {len(response.data)} 条记录"}
        
        else:
            return {"success": False, "msg": "未知操作类型"}
            
    except Exception as e:
        logger.error(f"批量操作失败: {str(e)}")
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
