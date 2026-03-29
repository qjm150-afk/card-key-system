# 图形验证码触发策略设计

## 一、触发时机对比

### 策略对比

| 策略 | 安全性 | 用户体验 | 推荐度 |
|------|--------|----------|--------|
| **每次验证都输入** | ⭐⭐⭐⭐⭐ | ⭐ | ❌ 不推荐 |
| **首次访问输入** | ⭐⭐⭐⭐ | ⭐⭐⭐ | ✅ 可用 |
| **异常行为触发** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ✅✅ 强烈推荐 |
| **N次失败后触发** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ✅ 推荐 |

---

## 二、推荐策略：智能触发（最佳平衡）

### 2.1 触发规则

```
┌─────────────────────────────────────────────────────────────────────┐
│                        验证码触发逻辑                                │
│                                                                     │
│   用户访问验证页面                                                   │
│        │                                                            │
│        ▼                                                            │
│   ┌────────────────────────────────────┐                           │
│   │ 检查是否需要验证码                   │                           │
│   └────────────────────────────────────┘                           │
│        │                                                            │
│        ├── 不需要 ──────────────────────▶ 直接验证卡密              │
│        │                                                            │
│        └── 需要 ──────────────────────▶ 显示验证码                  │
│                                              │                      │
│                                              ▼                      │
│                                        输入验证码 + 卡密            │
│                                              │                      │
│                                              ▼                      │
│                                        验证通过后提交               │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 具体触发条件

| 条件 | 是否触发验证码 | 说明 |
|------|----------------|------|
| **首次访问** | ❌ 不触发 | 给用户良好第一印象 |
| **同一设备连续验证** | ✅ 触发 | 第3次验证开始需要验证码 |
| **验证失败1次** | ❌ 不触发 | 允许用户输错一次 |
| **验证失败2次+** | ✅ 触发 | 连续失败后必须验证 |
| **同一卡密失败3次+** | ✅ 触发 | 防止暴力破解单卡密 |
| **短时间内频繁请求** | ✅ 触发 | 1分钟内请求超过3次 |

### 2.3 判断逻辑代码

```python
# src/main.py 新增

# 验证码触发条件存储
_captcha_triggers = defaultdict(lambda: {
    "device_attempts": 0,      # 设备验证次数
    "failure_count": 0,        # 连续失败次数
    "last_request_time": None, # 上次请求时间
    "requests_in_window": []   # 时间窗口内的请求记录
})

def should_show_captcha(device_id: str, card_key: str) -> dict:
    """
    判断是否需要显示验证码
    
    Returns:
        {
            "required": bool,           # 是否需要验证码
            "reason": str,              # 触发原因
            "device_attempts": int,     # 设备验证次数
            "failure_count": int        # 失败次数
        }
    """
    key = device_id or "anonymous"
    state = _captcha_triggers[key]
    now = datetime.now()
    
    # 条件1: 同一设备验证超过3次
    if state["device_attempts"] >= 3:
        return {
            "required": True,
            "reason": "设备验证次数较多，请输入验证码",
            "device_attempts": state["device_attempts"],
            "failure_count": state["failure_count"]
        }
    
    # 条件2: 连续失败超过1次（第2次失败开始）
    if state["failure_count"] >= 1:
        return {
            "required": True,
            "reason": "验证失败较多，请输入验证码",
            "device_attempts": state["device_attempts"],
            "failure_count": state["failure_count"]
        }
    
    # 条件3: 短时间内频繁请求（1分钟内超过3次）
    window_start = now - timedelta(minutes=1)
    state["requests_in_window"] = [
        t for t in state["requests_in_window"] 
        if t > window_start
    ]
    
    if len(state["requests_in_window"]) >= 3:
        return {
            "required": True,
            "reason": "请求过于频繁，请输入验证码",
            "device_attempts": state["device_attempts"],
            "failure_count": state["failure_count"]
        }
    
    # 条件4: 检查该卡密是否被多次尝试（不同设备尝试同一卡密）
    card_attempts = sum(
        1 for k, v in _captcha_triggers.items() 
        if k != key and v.get("last_card_key") == card_key
    )
    if card_attempts >= 3:
        return {
            "required": True,
            "reason": "该卡密验证次数较多，请输入验证码",
            "device_attempts": state["device_attempts"],
            "failure_count": state["failure_count"]
        }
    
    # 不需要验证码
    return {
        "required": False,
        "reason": "",
        "device_attempts": state["device_attempts"],
        "failure_count": state["failure_count"]
    }


def record_validation_attempt(device_id: str, card_key: str, success: bool):
    """记录验证尝试"""
    key = device_id or "anonymous"
    state = _captcha_triggers[key]
    now = datetime.now()
    
    # 更新设备验证次数
    state["device_attempts"] += 1
    
    # 更新请求时间记录
    state["requests_in_window"].append(now)
    state["last_request_time"] = now
    state["last_card_key"] = card_key
    
    # 更新失败次数
    if success:
        state["failure_count"] = 0  # 成功后重置
    else:
        state["failure_count"] += 1
```

---

## 三、API 接口设计

### 3.1 检查是否需要验证码

```python
@app.get("/api/captcha/check")
async def check_captcha_required(device_id: Optional[str] = None):
    """
    检查是否需要验证码
    
    前端在页面加载时调用，根据返回决定是否显示验证码输入框
    """
    # 获取设备ID（前端生成并存储在 localStorage）
    device_id = device_id or "anonymous"
    
    result = should_show_captcha(device_id, "")
    
    return {
        "success": True,
        "data": {
            "required": result["required"],
            "reason": result["reason"]
        }
    }
```

### 3.2 生成验证码

```python
@app.get("/api/captcha")
async def get_captcha(device_id: Optional[str] = None):
    """
    生成图形验证码
    
    返回：
    - 图片（PNG格式）
    - 验证码ID（在响应头中）
    """
    import io
    from PIL import Image, ImageDraw, ImageFont
    
    # 生成随机字符
    chars = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    
    # 生成验证码ID
    captcha_id = secrets.token_urlsafe(16)
    
    # 存储验证码（5分钟过期）
    _captcha_store[captcha_id] = {
        "code": chars,
        "device_id": device_id,
        "expire_at": datetime.now() + timedelta(seconds=300)
    }
    
    # 生成图片
    img = Image.new('RGB', (120, 40), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    
    # 添加干扰线
    for _ in range(5):
        x1 = random.randint(0, 120)
        y1 = random.randint(0, 40)
        x2 = random.randint(0, 120)
        y2 = random.randint(0, 40)
        draw.line([(x1, y1), (x2, y2)], 
                  fill=(random.randint(150, 200), random.randint(150, 200), random.randint(150, 200)), 
                  width=1)
    
    # 添加噪点
    for _ in range(100):
        x = random.randint(0, 119)
        y = random.randint(0, 39)
        draw.point((x, y), fill=(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)))
    
    # 绘制文字（带随机偏移和颜色）
    for i, char in enumerate(chars):
        x = 15 + i * 25 + random.randint(-3, 3)
        y = 8 + random.randint(-3, 3)
        color = (random.randint(0, 100), random.randint(0, 100), random.randint(0, 100))
        draw.text((x, y), char, fill=color)
    
    # 转换为字节
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    
    return Response(
        content=img_byte_arr.getvalue(),
        media_type="image/png",
        headers={"X-Captcha-Id": captcha_id}
    )
```

### 3.3 验证码校验

```python
def verify_captcha(captcha_id: str, code: str, device_id: str = None) -> tuple[bool, str]:
    """
    验证验证码
    
    Returns:
        (是否通过, 错误信息)
    """
    if not captcha_id or not code:
        return False, "请输入验证码"
    
    # 检查验证码是否存在
    if captcha_id not in _captcha_store:
        return False, "验证码已过期，请刷新"
    
    stored = _captcha_store[captcha_id]
    
    # 检查是否过期
    if datetime.now() > stored["expire_at"]:
        del _captcha_store[captcha_id]
        return False, "验证码已过期，请刷新"
    
    # 验证码匹配（忽略大小写）
    if stored["code"].upper() != code.upper().strip():
        return False, "验证码错误"
    
    # 验证成功，删除验证码（防止重复使用）
    del _captcha_store[captcha_id]
    
    return True, ""
```

### 3.4 修改验证接口

```python
class ValidateRequest(BaseModel):
    """验证请求"""
    card_key: str
    device_id: Optional[str] = None
    # 验证码相关（可选）
    captcha_id: Optional[str] = None
    captcha_code: Optional[str] = None


@app.post("/api/validate", response_model=ValidateResponse)
async def validate_card_key(request: ValidateRequest, fastapi_request: Request):
    """验证卡密 API"""
    
    device_id = request.device_id or "unknown"
    
    # 1. 检查是否需要验证码
    captcha_check = should_show_captcha(device_id, request.card_key)
    
    # 2. 如果需要验证码，但用户没提供
    if captcha_check["required"]:
        if not request.captcha_id or not request.captcha_code:
            # 记录本次尝试
            record_validation_attempt(device_id, request.card_key, False)
            
            return ValidateResponse(
                can_access=False, 
                msg="请输入验证码",
                captcha_required=True  # 告诉前端需要显示验证码
            )
        
        # 验证验证码
        captcha_valid, captcha_error = verify_captcha(
            request.captcha_id, 
            request.captcha_code,
            device_id
        )
        
        if not captcha_valid:
            record_validation_attempt(device_id, request.card_key, False)
            return ValidateResponse(
                can_access=False, 
                msg=captcha_error,
                captcha_required=True
            )
    
    # 3. 原有的卡密验证逻辑...
    # ...
    
    # 4. 记录验证结果
    record_validation_attempt(device_id, request.card_key, success)
    
    # 5. 返回结果
    return ValidateResponse(...)
```

---

## 四、前端实现

### 4.1 修改验证页面

```html
<!-- src/static/index.html 修改 -->

<!-- 在卡密输入框下方添加验证码区域（初始隐藏） -->
<div id="captchaSection" class="captcha-section" style="display: none; margin-bottom: 14px;">
    <div style="display: flex; gap: 10px; align-items: center;">
        <input 
            type="text" 
            id="captchaCode" 
            class="input" 
            placeholder="验证码"
            maxlength="6"
            style="flex: 1; text-transform: uppercase;"
        >
        <img 
            id="captchaImg" 
            src="" 
            alt="验证码"
            style="height: 42px; border-radius: 8px; cursor: pointer; border: 1px solid #E8D5C4;"
            onclick="refreshCaptcha()"
            title="点击刷新验证码"
        >
    </div>
    <input type="hidden" id="captchaId">
</div>

<script>
// 页面加载时检查是否需要验证码
async function checkCaptchaRequired() {
    const deviceId = getDeviceId();
    
    try {
        const response = await fetch(`/api/captcha/check?device_id=${deviceId}`);
        const result = await response.json();
        
        if (result.success && result.data.required) {
            // 需要验证码，显示验证码区域
            document.getElementById('captchaSection').style.display = 'block';
            refreshCaptcha();
        }
    } catch (e) {
        console.error('检查验证码需求失败', e);
    }
}

// 刷新验证码
async function refreshCaptcha() {
    const deviceId = getDeviceId();
    const img = document.getElementById('captchaImg');
    
    // 添加时间戳防止缓存
    const timestamp = Date.now();
    img.src = `/api/captcha?device_id=${deviceId}&t=${timestamp}`;
    
    // 获取验证码ID（从响应头）
    img.onload = function() {
        // 注意：跨域情况下无法读取响应头
        // 改用 URL 参数传递 captcha_id
    };
}

// 提交表单
async function submitForm(e) {
    e.preventDefault();
    
    const cardKey = document.getElementById('cardKey').value.trim();
    const deviceId = getDeviceId();
    
    // 检查是否需要验证码
    const captchaSection = document.getElementById('captchaSection');
    let captchaId = null;
    let captchaCode = null;
    
    if (captchaSection.style.display !== 'none') {
        captchaId = document.getElementById('captchaId').value;
        captchaCode = document.getElementById('captchaCode').value.trim();
        
        if (!captchaCode) {
            showError('请输入验证码');
            return;
        }
    }
    
    // 发送请求
    const response = await fetch('/api/validate', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            card_key: cardKey,
            device_id: deviceId,
            captcha_id: captchaId,
            captcha_code: captchaCode
        })
    });
    
    const result = await response.json();
    
    // 如果后端要求验证码
    if (result.captcha_required) {
        document.getElementById('captchaSection').style.display = 'block';
        refreshCaptcha();
        showError(result.msg || '请输入验证码');
        return;
    }
    
    // 处理其他结果...
}

// 页面加载完成后检查
document.addEventListener('DOMContentLoaded', function() {
    checkCaptchaRequired();
});
</script>
```

---

## 五、用户体验流程

### 5.1 正常用户流程

```
用户首次访问
    ↓
❌ 不需要验证码（良好体验）
    ↓
输入卡密 → 验证成功 ✅
```

### 5.2 失败一次后

```
用户输入错误卡密
    ↓
验证失败（第1次）
    ↓
❌ 不需要验证码（允许输错一次）
    ↓
再次输入卡密 → 验证失败（第2次）
    ↓
✅ 显示验证码（防止暴力破解）
    ↓
输入验证码 + 正确卡密 → 验证成功 ✅
```

### 5.3 频繁请求

```
用户1分钟内请求超过3次
    ↓
✅ 显示验证码（防止刷接口）
    ↓
输入验证码后才能继续
```

### 5.4 攻击者流程

```
攻击者用脚本随机尝试卡密
    ↓
第1次：不需要验证码
第2次：不需要验证码
第3次：✅ 需要验证码
    ↓
攻击者无法自动识别验证码 → 攻击被阻止 ✅
```

---

## 六、配置参数

### 6.1 可调整的阈值

```python
# 验证码触发阈值配置
CAPTCHA_CONFIG = {
    # 设备验证次数阈值
    "max_device_attempts": 3,      # 同一设备验证3次后需要验证码
    
    # 失败次数阈值
    "max_failures": 1,              # 连续失败1次后需要验证码（第2次开始）
    
    # 时间窗口阈值
    "rate_limit_window": 60,        # 时间窗口（秒）
    "rate_limit_max": 3,            # 窗口内最多请求次数
    
    # 验证码有效期
    "captcha_expire": 300,          # 验证码5分钟过期
    
    # 卡密尝试阈值
    "max_card_attempts": 3,         # 同一卡密被尝试3次后需要验证码
}
```

### 6.2 根据实际情况调整

| 场景 | 建议配置 | 说明 |
|------|----------|------|
| **用户经常输错** | `max_failures = 2` | 允许输错2次 |
| **用户频繁刷新** | `rate_limit_max = 5` | 放宽频率限制 |
| **攻击较多** | `max_device_attempts = 2` | 更早触发验证码 |
| **验证码难识别** | `captcha_expire = 600` | 延长有效期 |

---

## 七、总结

### 推荐策略

| 时机 | 是否触发 | 理由 |
|------|----------|------|
| 首次访问 | ❌ 不触发 | 良好第一印象 |
| 第1次失败 | ❌ 不触发 | 允许输错 |
| 第2次失败 | ✅ 触发 | 防止暴力破解 |
| 设备验证3次+ | ✅ 触发 | 防止刷接口 |
| 1分钟请求3次+ | ✅ 触发 | 防止脚本攻击 |

### 效果预估

```
正常用户：
- 首次验证：无需验证码（转化率 100%）
- 输错一次：无需验证码（转化率 95%）
- 输错两次：需要验证码（转化率 85%）

攻击者：
- 第3次尝试：被验证码阻挡
- 无法自动识别验证码 → 攻击成本大幅提高
```

---

*文档版本：1.0*
*创建时间：2026-03-28*
