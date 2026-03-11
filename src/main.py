"""
卡密验证系统 - 主入口
使用 FastAPI + Supabase 连接 Coze 内置数据库
"""

import os
import sys
import logging
from typing import Optional
from fastapi import FastAPI, HTTPException
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


# ==================== 静态文件服务 ====================

@app.get("/")
async def serve_index():
    """服务首页"""
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path, media_type="text/html")
    raise HTTPException(status_code=404, detail="Index page not found")


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
