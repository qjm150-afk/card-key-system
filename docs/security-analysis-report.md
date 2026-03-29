# 系统安全防护分析报告

## 一、现有安全机制

### 1.1 已实现的安全措施

| 安全措施 | 实现位置 | 配置参数 |
|----------|----------|----------|
| **API 限流** | `RateLimitMiddleware` | 60秒内最多10次请求 |
| **登录保护** | `record_login_failure()` | 5次失败后锁定15分钟 |
| **中间件链** | `TimingMiddleware` | 请求计时和日志 |

### 1.2 API 限流实现细节

**代码位置**：`src/main.py` 第 244-298 行

```python
# 限流规则配置
RATE_LIMITS = {
    "/api/validate": {"requests": 10, "window": 60},  # 验证接口：60秒内最多10次
}

class RateLimitMiddleware(BaseHTTPMiddleware):
    """API 限流中间件 - 防止暴力破解（合规：不收集 IP）"""
    
    RATE_LIMITED_PATHS = ["/api/validate"]
    
    async def dispatch(self, request, call_next):
        if path in self.RATE_LIMITED_PATHS:
            # 获取客户端标识（合规：使用 card_key，不使用 IP）
            identifier = "anonymous"
            if request.method == "POST":
                body = await request.body()
                data = json.loads(body)
                card_key = data.get("card_key", "")
                if card_key:
                    identifier = f"card:{card_key[:8]}"  # 只取前8位
            
            # 检查限流
            allowed, retry_after = check_rate_limit(identifier, path)
            
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={"success": False, "msg": f"请求过于频繁，请 {retry_after} 秒后重试"}
                )
```

### 1.3 登录安全实现细节

**代码位置**：`src/main.py` 第 224-243 行

```python
# 安全配置
MAX_LOGIN_FAILURES = 5       # 最大失败次数
LOCKOUT_DURATION = 900       # 锁定时长（秒），15分钟
FAILURE_WINDOW = 300         # 失败计数窗口（秒），5分钟

# 固定标识符（不收集 IP，使用固定 key 进行全局限流）
LOGIN_SECURITY_KEY = "admin_login_global"
```

---

## 二、安全漏洞分析

### 2.1 严重问题：限流标识可绕过

**问题描述**：

限流标识使用 `card_key` 而非 `IP`，攻击者可以通过以下方式绕过限流：

```
攻击者脚本逻辑：
1. 生成随机卡密：CSS-XXXX-XXXX-XXXX
2. 每次使用不同的卡密前8位
3. 限流标识每次都不同 → 永远不会被限流
```

**攻击场景**：

```python
# 攻击脚本示例
import requests
import random
import string

def generate_random_card_key():
    """生成随机卡密"""
    prefix = "CSS"
    parts = [''.join(random.choices(string.ascii_uppercase + string.digits, k=4)) for _ in range(3)]
    return f"{prefix}-{'-'.join(parts)}"

# 攻击循环
for i in range(100000):  # 发送10万次请求
    card_key = generate_random_card_key()
    response = requests.post('https://your-site.com/api/validate', 
                            json={'card_key': card_key, 'device_id': 'test'})
    print(f"Request {i}: {response.status_code}")
```

**结果**：
- ✅ 攻击成功：每次请求的限流标识都不同
- ❌ 防护失效：永远不会触发 429 限流
- ⚠️ 后果：数据库被打满，FC 服务瘫痪

### 2.2 严重问题：无图形验证码

**问题描述**：

验证页面没有任何人机验证机制，自动化脚本可以无成本刷接口。

**代码证据**：

查看 `src/static/index.html`，验证表单只有：

```html
<form id="validateForm">
    <input type="text" id="cardKey" placeholder="请输入您的专属卡密">
    <button type="submit">立即解锁</button>
    <!-- ❌ 没有任何验证码组件 -->
</form>
```

**攻击场景**：

```
攻击者可以：
1. 使用 Selenium / Puppeteer 自动化工具
2. 直接调用 API 接口（无需浏览器）
3. 无任何成本地发送大量请求
```

### 2.3 中等问题：登录安全基于固定标识

**问题描述**：

登录安全使用固定的 `LOGIN_SECURITY_KEY`，而非 IP 地址。

```python
LOGIN_SECURITY_KEY = "admin_login_global"
```

**影响**：

| 场景 | 正常情况 | 当前实现 |
|------|----------|----------|
| 用户A登录失败5次 | 只锁定用户A | 锁定所有人 |
| 攻击者暴力破解 | 只锁定攻击者IP | 锁定所有人 |
| 合法用户尝试登录 | 可以登录 | 无法登录（被全局锁定） |

**潜在问题**：

- 攻击者可以故意触发锁定，导致管理员无法登录后台
- 这是一个 **拒绝服务攻击** 漏洞

---

## 三、根本原因：合规性设计冲突

### 3.1 代码中的合规说明

**代码位置**：`src/main.py` 第 291-293 行

```python
# 获取客户端标识（合规：使用 card_key，不使用 IP）
identifier = "anonymous"
```

**代码位置**：`src/main.py` 第 224-225 行

```python
# 登录失败计数存储（合规：不收集 IP，使用固定标识）
_login_failures = defaultdict(list)
```

**代码位置**：`src/main.py` 访问日志部分

```python
def log_access(client, card_key_id, key_value, success, error_msg, device_id=None, sales_channel=None, is_first_access=False):
    """记录访问日志
    
    注意：根据《个人信息保护法》合规要求，不再收集IP地址、User-Agent、设备类型
    """
```

### 3.2 合规性与安全性的冲突

| 维度 | 合规要求 | 安全需求 | 当前实现 |
|------|----------|----------|----------|
| IP 地址 | 不收集 | 需要用于限流 | ❌ 不收集 |
| User-Agent | 不收集 | 可用于识别脚本 | ❌ 不收集 |
| 设备指纹 | 可以收集 | 可用于限流 | ✅ 已收集 |
| 验证码 | 无限制 | 必须要有 | ❌ 没有 |

---

## 四、风险评估

### 4.1 风险矩阵

| 攻击类型 | 可能性 | 影响 | 风险等级 |
|----------|--------|------|----------|
| 暴力破解卡密 | 高 | 高 | **严重** |
| 接口刷量攻击 | 高 | 高 | **严重** |
| 拒绝服务攻击 | 中 | 高 | **高** |
| 管理后台锁定 | 中 | 中 | **中** |

### 4.2 潜在损失

| 损失类型 | 描述 |
|----------|------|
| **服务瘫痪** | FC 服务被打满，正常用户无法验证 |
| **数据泄露** | 暴力破解成功后，飞书内容被访问 |
| **经济损失** | FC 费用暴增（按量付费） |
| **用户体验** | 正常用户无法使用 |

---

## 五、解决方案

### 方案A：保持合规性，增加其他防护

**适用场景**：严格遵守《个人信息保护法》，不接受任何 IP 收集

**措施**：

| 措施 | 效果 | 实现难度 |
|------|------|----------|
| 1. 增加图形验证码 | 阻止自动化脚本 | ⭐⭐ |
| 2. 增加滑块验证 | 更好的用户体验 | ⭐⭐⭐ |
| 3. 基于设备指纹限流 | 替代 IP 限流 | ⭐⭐ |
| 4. 增加请求签名验证 | 防止直接 API 调用 | ⭐⭐⭐ |

**推荐组合**：图形验证码 + 设备指纹限流

### 方案B：合规性变通，收集非个人信息

**适用场景**：愿意接受一定程度的 IP 收集（仅用于安全防护）

**法律依据**：

根据《个人信息保护法》和《网络安全法》：

1. **IP 地址属于个人信息**，但：
   - 收集目的明确（安全防护）
   - 不存储、不关联用户身份
   - 仅用于临时限流

2. **合规实践**：
   - 在隐私政策中说明
   - IP 仅存在于内存中（不持久化）
   - 限流窗口过期后自动删除

**措施**：

```python
# 合规的 IP 限流实现
class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # 获取 IP（仅用于内存中的限流，不存储到数据库）
        ip = request.client.host if request.client else "unknown"
        
        # 限流标识：IP + 卡密前缀（双重限流）
        card_key_prefix = extract_card_key_prefix(request)
        identifier = f"{ip}:{card_key_prefix}"
        
        # 限流检查...
        # 注意：IP 仅存在于 _rate_limit_store 内存字典中
        #       不会写入数据库或日志文件
```

### 方案C：混合方案（推荐）

**适用场景**：平衡合规性和安全性

**措施**：

| 层级 | 措施 | 说明 |
|------|------|------|
| **第一层** | 图形验证码 | 阻止低端脚本 |
| **第二层** | 设备指纹限流 | 每个设备每分钟最多10次 |
| **第三层** | 全局限流 | 整个接口每分钟最多1000次 |
| **第四层** | 异常检测 | 同一卡密失败N次后临时封禁 |

---

## 六、具体实施方案

### 6.1 方案一：增加图形验证码（最简单）

**技术选型**：

- **前端**：使用 `svg-captcha` 或 `TencentCaptcha`（腾讯验证码）
- **后端**：验证码校验中间件

**实现步骤**：

#### Step 1: 后端生成验证码

```python
# src/main.py 新增

import io
import random
import string
from PIL import Image, ImageDraw, ImageFont
from fastapi import Response

# 验证码存储（内存，不持久化）
_captcha_store = {}
CAPTCHA_EXPIRE = 300  # 5分钟过期

@app.get("/api/captcha")
async def get_captcha():
    """生成图形验证码"""
    # 生成随机字符
    chars = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    
    # 生成验证码ID
    captcha_id = secrets.token_urlsafe(16)
    
    # 存储验证码（内存）
    _captcha_store[captcha_id] = {
        "code": chars,
        "expire_at": datetime.now() + timedelta(seconds=CAPTCHA_EXPIRE)
    }
    
    # 生成图片
    img = Image.new('RGB', (120, 40), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    
    # 添加干扰线
    for _ in range(3):
        draw.line([(random.randint(0, 120), random.randint(0, 40)),
                   (random.randint(0, 120), random.randint(0, 40))],
                  fill=(200, 200, 200), width=1)
    
    # 绘制文字
    for i, char in enumerate(chars):
        draw.text((20 + i * 25, 10), char, fill=(0, 0, 0))
    
    # 转换为字节
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    
    return Response(
        content=img_byte_arr.getvalue(),
        media_type="image/png",
        headers={
            "X-Captcha-Id": captcha_id
        }
    )

def verify_captcha(captcha_id: str, code: str) -> bool:
    """验证验证码"""
    if captcha_id not in _captcha_store:
        return False
    
    stored = _captcha_store[captcha_id]
    
    # 检查是否过期
    if datetime.now() > stored["expire_at"]:
        del _captcha_store[captcha_id]
        return False
    
    # 验证码匹配（忽略大小写）
    if stored["code"].upper() != code.upper():
        return False
    
    # 验证成功后删除
    del _captcha_store[captcha_id]
    return True
```

#### Step 2: 修改验证接口

```python
# src/main.py 修改 ValidateRequest

class ValidateRequest(BaseModel):
    """验证请求"""
    card_key: str
    device_id: Optional[str] = None
    captcha_id: Optional[str] = None  # 新增：验证码ID
    captcha_code: Optional[str] = None  # 新增：验证码

@app.post("/api/validate", response_model=ValidateResponse)
async def validate_card_key(request: ValidateRequest, fastapi_request: Request):
    """验证卡密 API"""
    
    # 验证码检查
    if not request.captcha_id or not request.captcha_code:
        return ValidateResponse(can_access=False, msg="请输入验证码")
    
    if not verify_captcha(request.captcha_id, request.captcha_code):
        return ValidateResponse(can_access=False, msg="验证码错误或已过期")
    
    # 原有的验证逻辑...
```

#### Step 3: 前端添加验证码

```html
<!-- src/static/index.html 修改 -->

<div class="captcha-row" style="display: flex; gap: 10px; margin-bottom: 14px;">
    <input type="text" id="captchaCode" class="input" placeholder="验证码" style="flex: 1;">
    <img id="captchaImg" src="/api/captcha" 
         style="height: 42px; border-radius: 8px; cursor: pointer;"
         onclick="refreshCaptcha()">
</div>

<script>
// 刷新验证码
function refreshCaptcha() {
    const img = document.getElementById('captchaImg');
    img.src = '/api/captcha?t=' + Date.now();
}

// 提交时带上验证码
async function submitForm() {
    const response = await fetch('/api/validate', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            card_key: cardKey,
            device_id: deviceId,
            captcha_id: document.getElementById('captchaImg').getAttribute('x-captcha-id'),
            captcha_code: document.getElementById('captchaCode').value
        })
    });
}
</script>
```

### 6.2 方案二：基于设备指纹的限流

```python
# src/main.py 修改 RateLimitMiddleware

class RateLimitMiddleware(BaseHTTPMiddleware):
    """API 限流中间件 - 基于设备指纹"""
    
    RATE_LIMITED_PATHS = ["/api/validate"]
    
    async def dispatch(self, request, call_next):
        path = request.url.path
        
        if path in self.RATE_LIMITED_PATHS:
            # 优先使用设备指纹
            device_id = None
            if request.method == "POST":
                try:
                    body = await request.body()
                    if body:
                        data = json.loads(body)
                        device_id = data.get("device_id")
                except:
                    pass
            
            # 设备指纹限流（更严格）
            if device_id:
                identifier = f"device:{device_id}"
                config = {"requests": 10, "window": 60}  # 每设备每分钟10次
            else:
                # 没有设备指纹，使用全局限流
                identifier = "global"
                config = {"requests": 1000, "window": 60}  # 全局每分钟1000次
            
            # 检查限流
            allowed, retry_after = check_rate_limit_with_config(identifier, path, config)
            
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={"success": False, "msg": f"请求过于频繁，请 {retry_after} 秒后重试"}
                )
        
        return await call_next(request)
```

### 6.3 方案三：卡密失败次数封禁

```python
# src/main.py 新增

# 卡密失败计数（内存，不持久化）
_card_key_failures = defaultdict(int)
CARD_KEY_BAN_THRESHOLD = 10  # 连续失败10次后封禁
CARD_KEY_BAN_DURATION = 300  # 封禁5分钟

def check_card_key_banned(card_key: str) -> bool:
    """检查卡密是否被封禁"""
    key = f"ban:{card_key}"
    return key in _login_lockouts

def ban_card_key(card_key: str):
    """封禁卡密"""
    key = f"ban:{card_key}"
    _login_lockouts[key] = datetime.now() + timedelta(seconds=CARD_KEY_BAN_DURATION)

def record_card_key_failure(card_key: str):
    """记录卡密验证失败"""
    _card_key_failures[card_key] += 1
    
    if _card_key_failures[card_key] >= CARD_KEY_BAN_THRESHOLD:
        ban_card_key(card_key)
        logger.warning(f"[Security] 卡密 {card_key} 因连续失败被临时封禁")

@app.post("/api/validate")
async def validate_card_key(request: ValidateRequest):
    # 检查是否被封禁
    if check_card_key_banned(request.card_key):
        return ValidateResponse(can_access=False, msg="该卡密已被临时封禁，请稍后再试")
    
    # 验证逻辑...
    
    # 失败时记录
    if not success:
        record_card_key_failure(request.card_key)
```

---

## 七、推荐实施优先级

| 优先级 | 措施 | 效果 | 工作量 |
|--------|------|------|--------|
| **P0** | 增加图形验证码 | 阻止90%的脚本攻击 | 2-3小时 |
| **P1** | 卡密失败次数封禁 | 防止单卡密被暴力破解 | 1小时 |
| **P2** | 基于设备指纹限流 | 替代IP限流 | 1小时 |
| **P3** | 全局限流兜底 | 防止服务被打满 | 0.5小时 |
| **P4** | 使用第三方验证码 | 更好的用户体验 | 需要付费 |

---

## 八、总结

### 8.1 现有安全机制评估

| 项目 | 状态 | 评分 |
|------|------|------|
| API 限流 | ⚠️ 存在但可绕过 | 3/10 |
| 登录保护 | ⚠️ 全局锁定有风险 | 5/10 |
| 图形验证码 | ❌ 未实现 | 0/10 |
| IP 封禁 | ❌ 因合规未实现 | N/A |
| 设备指纹 | ✅ 已收集但未用于安全 | 7/10 |

### 8.2 风险等级

**当前风险等级：高**

- 暴力破解攻击：**可实施**
- 接口刷量攻击：**可实施**
- 拒绝服务攻击：**可实施**

### 8.3 建议

**立即实施**：

1. ✅ 增加图形验证码（最小改动，最大效果）
2. ✅ 增加卡密失败次数封禁
3. ✅ 增加全局限流兜底

**后续优化**：

1. 考虑使用第三方验证码服务
2. 完善设备指纹限流逻辑
3. 添加异常行为检测

---

*文档版本：1.0*
*创建时间：2026-03-28*
