"""
验证码模块 - 自建图形验证码

功能：
1. 生成图形验证码（随机4位数字字母组合）
2. 校验验证码
3. 验证码触发策略（智能触发）
4. 会话Token管理（已登录用户跳过验证码）

合规：不收集IP地址、UA等个人信息
"""

import random
import string
import hashlib
import base64
import io
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple
from PIL import Image, ImageDraw, ImageFont
import threading


# ==================== 辅助函数 ====================

def parse_datetime(dt_str: str) -> Optional[datetime]:
    """
    解析日期时间字符串（兼容多种格式）
    
    Args:
        dt_str: 日期时间字符串
    
    Returns:
        datetime对象，解析失败返回None
    """
    if not dt_str:
        return None
    
    # 尝试多种格式
    formats = [
        "%Y-%m-%dT%H:%M:%S.%f%z",  # ISO格式带时区
        "%Y-%m-%dT%H:%M:%S%z",      # ISO格式带时区（无毫秒）
        "%Y-%m-%dT%H:%M:%S.%f",     # ISO格式无时区
        "%Y-%m-%dT%H:%M:%S",        # ISO格式无时区（无毫秒）
        "%Y-%m-%d %H:%M:%S",        # 常规格式
    ]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(dt_str, fmt)
            # 如果没有时区信息，假定为本地时间
            return dt
        except ValueError:
            continue
    
    return None


# ==================== 验证码存储 ====================

# 验证码存储（内存字典，生产环境可替换为 Redis）
_captcha_store: Dict[str, dict] = {}  # {captcha_id: {code, expire_at, verified}}
_captcha_lock = threading.Lock()

# 验证码有效期（秒）
CAPTCHA_EXPIRE_SECONDS = 300  # 5分钟

# 验证码触发状态存储
_captcha_triggers: Dict[str, dict] = {}  # {device_id: {failure_count, device_attempts, last_success_time, ...}}
_trigger_lock = threading.Lock()

# 会话Token有效期（天）
SESSION_EXPIRE_DAYS = 30


# ==================== 数据库客户端获取 ====================
def _get_db_client():
    """
    获取数据库客户端（延迟导入，避免循环依赖）
    """
    try:
        from storage.database.db_client import get_db_client
        client, _ = get_db_client()
        return client
    except Exception as e:
        import logging
        logging.error(f"[SessionToken] 获取数据库客户端失败: {str(e)}")
        return None


# ==================== 验证码生成 ====================

def generate_captcha_code(length: int = 4) -> str:
    """生成随机验证码（数字+大写字母，排除易混淆字符）"""
    # 排除易混淆字符：0, O, 1, I, L
    chars = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
    return ''.join(random.choice(chars) for _ in range(length))


def generate_captcha_image(code: str, width: int = 120, height: int = 48) -> str:
    """
    生成验证码图片（Base64编码）
    
    Args:
        code: 验证码文本
        width: 图片宽度
        height: 图片高度
    
    Returns:
        Base64编码的PNG图片
    """
    # 创建图片
    image = Image.new('RGB', (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(image)
    
    # 尝试使用系统字体，如果失败则使用默认字体
    try:
        # macOS / Linux
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 36)
    except:
        try:
            # Linux
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
        except:
            # 使用默认字体
            font = ImageFont.load_default()
    
    # 绘制干扰线
    for _ in range(5):
        x1 = random.randint(0, width)
        y1 = random.randint(0, height)
        x2 = random.randint(0, width)
        y2 = random.randint(0, height)
        draw.line([(x1, y1), (x2, y2)], fill=(200, 200, 200), width=1)
    
    # 绘制干扰点
    for _ in range(100):
        x = random.randint(0, width - 1)
        y = random.randint(0, height - 1)
        draw.point((x, y), fill=(random.randint(150, 255), random.randint(150, 255), random.randint(150, 255)))
    
    # 绘制验证码文字
    text_width = len(code) * 28  # 估算文字宽度
    x = (width - text_width) // 2
    y = (height - 36) // 2
    
    for i, char in enumerate(code):
        # 每个字符稍微偏移和旋转
        char_x = x + i * 28 + random.randint(-3, 3)
        char_y = y + random.randint(-5, 5)
        
        # 随机颜色（深色）
        color = (random.randint(0, 100), random.randint(0, 100), random.randint(0, 100))
        
        draw.text((char_x, char_y), char, font=font, fill=color)
    
    # 转换为Base64
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    img_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
    
    return f"data:image/png;base64,{img_base64}"


def create_captcha() -> Tuple[str, str]:
    """
    创建验证码
    
    Returns:
        (captcha_id, captcha_image_base64)
    """
    # 生成验证码ID和验证码文本
    captcha_id = hashlib.sha256(f"{time.time()}{random.random()}".encode()).hexdigest()[:32]
    code = generate_captcha_code()
    
    # 生成验证码图片
    image_base64 = generate_captcha_image(code)
    
    # 存储验证码
    expire_at = datetime.now() + timedelta(seconds=CAPTCHA_EXPIRE_SECONDS)
    
    with _captcha_lock:
        _captcha_store[captcha_id] = {
            "code": code.upper(),
            "expire_at": expire_at,
            "verified": False
        }
    
    return captcha_id, image_base64


def verify_captcha(captcha_id: str, code: str) -> Tuple[bool, str]:
    """
    验证验证码
    
    Args:
        captcha_id: 验证码ID
        code: 用户输入的验证码
    
    Returns:
        (是否验证成功, 错误信息)
    """
    if not captcha_id or not code:
        return False, "请输入验证码"
    
    with _captcha_lock:
        # 检查验证码是否存在
        if captcha_id not in _captcha_store:
            return False, "验证码已过期，请刷新"
        
        captcha_data = _captcha_store[captcha_id]
        
        # 检查是否已过期
        if datetime.now() > captcha_data["expire_at"]:
            del _captcha_store[captcha_id]
            return False, "验证码已过期，请刷新"
        
        # 检查是否已验证过（防止重复使用）
        if captcha_data["verified"]:
            return False, "验证码已使用，请刷新"
        
        # 验证码比对（不区分大小写）
        if captcha_data["code"].upper() != code.strip().upper():
            return False, "验证码错误"
        
        # 标记为已验证
        captcha_data["verified"] = True
    
    return True, ""


def cleanup_expired_captchas():
    """清理过期的验证码"""
    now = datetime.now()
    with _captcha_lock:
        expired_ids = [k for k, v in _captcha_store.items() if now > v["expire_at"]]
        for k in expired_ids:
            del _captcha_store[k]
    return len(expired_ids)


# ==================== 验证码触发策略 ====================

def should_show_captcha(device_id: str, card_key: str = "") -> dict:
    """
    判断是否需要显示验证码
    
    智能触发策略：
    1. 首次访问：不触发验证码
    2. 连续失败 >= 2次：触发验证码
    3. 同一设备验证次数 >= 3次：触发验证码
    4. 24小时内验证成功过：跳过验证码
    
    Args:
        device_id: 设备ID
        card_key: 卡密（可选，用于记录）
    
    Returns:
        {
            "required": bool,  # 是否需要验证码
            "reason": str,     # 原因说明
            "skip_captcha": bool  # 是否跳过验证码检查
        }
    """
    key = device_id or "anonymous"
    
    with _trigger_lock:
        state = _captcha_triggers.get(key, {})
        
        # 条件1: 24小时内验证成功过，跳过验证码
        if state.get("last_success_time"):
            success_time = state["last_success_time"]
            if datetime.now() - success_time < timedelta(hours=24):
                return {
                    "required": False,
                    "reason": "近期已验证成功",
                    "skip_captcha": True
                }
        
        # 条件2: 连续失败 >= 2次，触发验证码
        if state.get("failure_count", 0) >= 2:
            return {
                "required": True,
                "reason": "验证失败次数较多，请完成验证码验证"
            }
        
        # 条件3: 同一设备验证次数 >= 3次，触发验证码
        if state.get("device_attempts", 0) >= 3:
            return {
                "required": True,
                "reason": "该设备验证次数较多，请完成验证码验证"
            }
        
        # 不需要验证码
        return {
            "required": False,
            "reason": "无需验证码",
            "skip_captcha": False
        }


def record_validation_attempt(device_id: str, card_key: str, success: bool):
    """
    记录验证尝试
    
    Args:
        device_id: 设备ID
        card_key: 卡密
        success: 是否验证成功
    """
    key = device_id or "anonymous"
    
    with _trigger_lock:
        if key not in _captcha_triggers:
            _captcha_triggers[key] = {
                "failure_count": 0,
                "device_attempts": 0,
                "last_success_time": None
            }
        
        state = _captcha_triggers[key]
        
        # 更新设备验证次数
        state["device_attempts"] = state.get("device_attempts", 0) + 1
        
        if success:
            # 验证成功：重置失败计数，记录成功时间
            state["failure_count"] = 0
            state["last_success_time"] = datetime.now()
        else:
            # 验证失败：增加失败计数
            state["failure_count"] = state.get("failure_count", 0) + 1


# ==================== 会话Token管理 ====================

def _hash_card_key(card_key: str) -> str:
    """
    对卡密进行哈希处理（不存储明文）
    
    Args:
        card_key: 卡密明文
    
    Returns:
        哈希值（SHA256前32位）
    """
    return hashlib.sha256(card_key.encode()).hexdigest()[:32]


def create_session_token(device_id: str, card_key: str) -> str:
    """
    创建会话Token（持久化到数据库）
    
    Args:
        device_id: 设备ID
        card_key: 卡密
    
    Returns:
        会话Token
    """
    import secrets
    
    token = secrets.token_urlsafe(32)
    expire_at = datetime.now() + timedelta(days=SESSION_EXPIRE_DAYS)
    card_key_hash = _hash_card_key(card_key)
    
    # 存储到数据库
    try:
        client = _get_db_client()
        if client:
            client.table('session_tokens').insert({
                "token": token,
                "device_id": device_id,
                "card_key_hash": card_key_hash,
                "expire_at": expire_at.isoformat()
            }).execute()
        else:
            # 数据库不可用时，回退到内存存储
            logging.warning("[SessionToken] 数据库不可用，回退到内存存储")
            global _session_tokens_fallback
            if '_session_tokens_fallback' not in globals():
                _session_tokens_fallback = {}
            _session_tokens_fallback[token] = {
                "device_id": device_id,
                "card_key": card_key,
                "expire_at": expire_at
            }
    except Exception as e:
        import logging
        logging.error(f"[SessionToken] 创建会话Token失败: {str(e)}")
    
    return token


def verify_session_token(token: str, card_key: str = None) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    验证会话Token（从数据库查询）
    
    Args:
        token: 会话Token
        card_key: 可选，卡密明文（用于验证哈希）
    
    Returns:
        (是否有效, card_key, device_id)
        
    注意：
        由于数据库只存储哈希值，无法返回完整的card_key。
        如果需要验证卡密，请传入card_key参数进行哈希比对。
        返回的card_key实际上是传入的card_key（如果验证通过）。
    """
    if not token:
        return False, None, None
    
    try:
        client = _get_db_client()
        if not client:
            # 数据库不可用时，检查内存回退存储
            global _session_tokens_fallback
            if '_session_tokens_fallback' not in globals():
                return False, None, None
            
            fallback = _session_tokens_fallback.get(token)
            if not fallback:
                return False, None, None
            
            if datetime.now() > fallback["expire_at"]:
                del _session_tokens_fallback[token]
                return False, None, None
            
            return True, fallback["card_key"], fallback["device_id"]
        
        # 从数据库查询
        response = client.table('session_tokens').select('*').eq('token', token).execute()
        
        if not response.data:
            return False, None, None
        
        session = response.data[0]
        
        # 检查是否过期
        expire_at_str = session.get('expire_at')
        if expire_at_str:
            # 处理时区问题
            expire_at = parse_datetime(expire_at_str)
            if expire_at and datetime.now() > expire_at:
                # 过期，删除记录
                client.table('session_tokens').delete().eq('token', token).execute()
                return False, None, None
        
        device_id = session.get('device_id')
        stored_hash = session.get('card_key_hash')
        
        # 如果提供了card_key，验证哈希
        if card_key:
            expected_hash = _hash_card_key(card_key)
            if stored_hash != expected_hash:
                return False, None, None
            return True, card_key, device_id
        
        # 没有提供card_key，只返回device_id（兼容旧逻辑）
        # 注意：这种情况下无法返回完整的card_key
        return True, None, device_id
        
    except Exception as e:
        import logging
        logging.error(f"[SessionToken] 验证会话Token失败: {str(e)}")
        return False, None, None


def revoke_session_token(token: str):
    """撤销会话Token（从数据库删除）"""
    try:
        client = _get_db_client()
        if client:
            client.table('session_tokens').delete().eq('token', token).execute()
        else:
            # 内存回退存储
            global _session_tokens_fallback
            if '_session_tokens_fallback' in globals() and token in _session_tokens_fallback:
                del _session_tokens_fallback[token]
    except Exception as e:
        import logging
        logging.error(f"[SessionToken] 撤销会话Token失败: {str(e)}")


def cleanup_expired_sessions():
    """清理过期的会话Token（从数据库删除）"""
    try:
        client = _get_db_client()
        if not client:
            # 内存回退存储
            global _session_tokens_fallback
            if '_session_tokens_fallback' not in globals():
                return 0
            now = datetime.now()
            expired = [k for k, v in _session_tokens_fallback.items() if now > v["expire_at"]]
            for k in expired:
                del _session_tokens_fallback[k]
            return len(expired)
        
        # 从数据库删除过期记录
        now = datetime.now().isoformat()
        response = client.table('session_tokens').delete().lt('expire_at', now).execute()
        return len(response.data) if response.data else 0
        
    except Exception as e:
        import logging
        logging.error(f"[SessionToken] 清理过期会话失败: {str(e)}")
        return 0


# ==================== 统计信息 ====================

def get_captcha_stats() -> dict:
    """获取验证码统计信息"""
    with _captcha_lock:
        captcha_count = len(_captcha_store)
    
    with _trigger_lock:
        trigger_count = len(_captcha_triggers)
    
    # 从数据库统计会话数量
    session_count = 0
    try:
        client = _get_db_client()
        if client:
            response = client.table('session_tokens').select('id', count='exact').execute()
            session_count = response.count if response.count else 0
        else:
            # 内存回退存储
            global _session_tokens_fallback
            if '_session_tokens_fallback' in globals():
                session_count = len(_session_tokens_fallback)
    except Exception as e:
        import logging
        logging.error(f"[SessionToken] 获取会话统计失败: {str(e)}")
    
    return {
        "captcha_count": captcha_count,
        "trigger_count": trigger_count,
        "session_count": session_count
    }
