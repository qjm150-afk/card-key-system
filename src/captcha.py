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

# ==================== 验证码存储 ====================

# 验证码存储（内存字典，生产环境可替换为 Redis）
_captcha_store: Dict[str, dict] = {}  # {captcha_id: {code, expire_at, verified}}
_captcha_lock = threading.Lock()

# 验证码有效期（秒）
CAPTCHA_EXPIRE_SECONDS = 300  # 5分钟

# 验证码触发状态存储
_captcha_triggers: Dict[str, dict] = {}  # {device_id: {failure_count, device_attempts, last_success_time, ...}}
_trigger_lock = threading.Lock()

# 会话Token存储
_session_tokens: Dict[str, dict] = {}  # {token: {device_id, card_key, expire_at}}
_session_lock = threading.Lock()

# 会话Token有效期（天）
SESSION_EXPIRE_DAYS = 30


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

def create_session_token(device_id: str, card_key: str) -> str:
    """
    创建会话Token
    
    Args:
        device_id: 设备ID
        card_key: 卡密
    
    Returns:
        会话Token
    """
    import secrets
    token = secrets.token_urlsafe(32)
    
    expire_at = datetime.now() + timedelta(days=SESSION_EXPIRE_DAYS)
    
    with _session_lock:
        _session_tokens[token] = {
            "device_id": device_id,
            "card_key": card_key,
            "expire_at": expire_at
        }
    
    return token


def verify_session_token(token: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    验证会话Token
    
    Args:
        token: 会话Token
    
    Returns:
        (是否有效, card_key, device_id)
    """
    if not token:
        return False, None, None
    
    with _session_lock:
        # 检查Token是否存在
        if token not in _session_tokens:
            return False, None, None
        
        session = _session_tokens[token]
        
        # 检查是否过期
        if datetime.now() > session["expire_at"]:
            del _session_tokens[token]
            return False, None, None
        
        return True, session["card_key"], session["device_id"]


def revoke_session_token(token: str):
    """撤销会话Token"""
    with _session_lock:
        if token in _session_tokens:
            del _session_tokens[token]


def cleanup_expired_sessions():
    """清理过期的会话Token"""
    now = datetime.now()
    with _session_lock:
        expired_tokens = [k for k, v in _session_tokens.items() if now > v["expire_at"]]
        for k in expired_tokens:
            del _session_tokens[k]
    return len(expired_tokens)


# ==================== 统计信息 ====================

def get_captcha_stats() -> dict:
    """获取验证码统计信息"""
    with _captcha_lock:
        captcha_count = len(_captcha_store)
    
    with _trigger_lock:
        trigger_count = len(_captcha_triggers)
    
    with _session_lock:
        session_count = len(_session_tokens)
    
    return {
        "captcha_count": captcha_count,
        "trigger_count": trigger_count,
        "session_count": session_count
    }
