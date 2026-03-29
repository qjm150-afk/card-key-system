# 验证码触发与会话保持分析

## 一、现有会话保持机制

### 1.1 会话存储

**代码位置**：`src/static/index.html`

```javascript
// 会话过期时间（30天）
const SESSION_EXPIRE_DAYS = 30;
const STORAGE_KEY = 'card_key_session';
const DEVICE_ID_KEY = 'card_key_device_id';

// 保存会话到 localStorage
function saveSession(cardKey, url, password) {
    const session = {
        cardKey: cardKey,
        url: url,
        password: password,
        deviceId: getDeviceId(),
        expireAt: Date.now() + SESSION_EXPIRE_DAYS * 24 * 60 * 60 * 1000  // 30天后过期
    };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
}
```

### 1.2 页面加载时的逻辑

```javascript
// 页面加载时检查本地会话
async function checkSession() {
    const session = getLocalSession();
    
    if (session) {
        // 有本地会话，尝试验证
        try {
            const result = await validateCardKey(session.cardKey, false);
            if (!result.success) {
                // 卡密已失效，显示验证页面
                showValidate();
            }
            // 验证成功，showSuccess 已在 validateCardKey 中调用
        } catch (err) {
            // 网络错误，使用本地缓存的 URL
            showSuccess(session.url, session.password);
        }
    } else {
        // 没有本地会话，显示验证页面
        showValidate();
    }
}
```

---

## 二、回答你的问题

### Q: 用户登录后关闭浏览器，下次再打开会跳出验证码吗？

**答案：取决于验证码的实现方式**

| 场景 | 当前实现（无验证码） | 添加验证码后（需要修改） |
|------|---------------------|------------------------|
| 用户已登录，关闭浏览器后再打开 | ✅ 自动恢复，无需验证 | ⚠️ 需要修改才能实现 |
| 用户首次访问 | 显示验证页面 | 可能显示验证码 |
| 用户会话过期（30天后） | 显示验证页面 | 显示验证码 |

---

## 三、问题分析

### 3.1 当前流程（无验证码）

```
用户首次访问
    ↓
输入卡密验证
    ↓
验证成功 → 保存会话到 localStorage（30天）
    ↓
关闭浏览器
    ↓
下次打开网站
    ↓
从 localStorage 读取会话
    ↓
自动调用验证接口
    ↓
验证成功 → 直接显示飞书内容 ✅
```

### 3.2 添加验证码后的潜在问题

**问题1：自动验证可能被验证码阻止**

```javascript
// 当前的自动验证逻辑
async function checkSession() {
    const session = getLocalSession();
    if (session) {
        // 调用验证接口，但没有提供验证码
        const result = await validateCardKey(session.cardKey, false);
        // ...
    }
}
```

**问题2：验证码触发条件会被"正常用户"触发**

```
用户 A：
- 第1天访问：验证成功
- 第2天访问：自动验证（第2次验证）
- 第3天访问：自动验证（第3次验证）
- 第4天访问：自动验证（第4次验证）→ 触发验证码！❌
```

---

## 四、解决方案

### 4.1 方案一：为已登录用户跳过验证码（推荐）

**修改后端验证逻辑**：

```python
def should_show_captcha(device_id: str, card_key: str) -> dict:
    """
    判断是否需要显示验证码
    
    核心原则：已验证成功的用户，下次访问不需要验证码
    """
    key = device_id or "anonymous"
    state = _captcha_triggers.get(key, {})
    
    # 【新增】检查是否有该设备的成功验证记录
    # 如果设备之前验证成功过，跳过验证码检查
    if state.get("last_success_time"):
        # 24小时内验证成功过，不需要验证码
        success_time = state["last_success_time"]
        if datetime.now() - success_time < timedelta(hours=24):
            return {
                "required": False,
                "reason": "近期已验证成功",
                "skip_captcha": True
            }
    
    # 原有的触发条件...
    # 条件1: 同一设备验证超过3次
    if state.get("device_attempts", 0) >= 3:
        return {"required": True, "reason": "设备验证次数较多"}
    
    # 条件2: 连续失败超过1次
    if state.get("failure_count", 0) >= 1:
        return {"required": True, "reason": "验证失败较多"}
    
    # ... 其他条件
```

**修改验证成功后的记录**：

```python
@app.post("/api/validate")
async def validate_card_key(request: ValidateRequest):
    # ... 验证逻辑
    
    if success:
        # 记录验证成功时间（用于下次跳过验证码）
        key = request.device_id or "unknown"
        _captcha_triggers[key]["last_success_time"] = datetime.now()
        _captcha_triggers[key]["failure_count"] = 0  # 重置失败计数
        
        # ... 返回成功
```

### 4.2 方案二：前端自动验证时跳过验证码检查

**修改前端验证逻辑**：

```javascript
// 验证卡密
async function validateCardKey(cardKey, saveSessionFlag = true, skipCaptchaCheck = false) {
    const deviceId = getDeviceId();
    
    const requestBody = { 
        card_key: cardKey,
        device_id: deviceId 
    };
    
    // 如果是自动验证（恢复会话），告诉后端跳过验证码检查
    if (skipCaptchaCheck) {
        requestBody.skip_captcha_check = true;
    }
    
    const response = await fetch('/api/validate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestBody),
    });
    
    // ...
}

// 页面加载时检查会话
async function checkSession() {
    const session = getLocalSession();
    
    if (session) {
        // 自动验证时，跳过验证码检查
        const result = await validateCardKey(session.cardKey, false, true);
        // ...
    }
}
```

**修改后端验证逻辑**：

```python
class ValidateRequest(BaseModel):
    card_key: str
    device_id: Optional[str] = None
    captcha_id: Optional[str] = None
    captcha_code: Optional[str] = None
    skip_captcha_check: Optional[bool] = False  # 新增：跳过验证码检查

@app.post("/api/validate")
async def validate_card_key(request: ValidateRequest):
    device_id = request.device_id or "unknown"
    
    # 检查是否需要验证码
    captcha_check = should_show_captcha(device_id, request.card_key)
    
    # 【新增】如果是自动验证（恢复会话），跳过验证码
    if request.skip_captcha_check:
        # 但是需要验证卡密是否有效（后端验证）
        # 不能只依赖前端的 skip_captcha_check
        pass  # 继续验证卡密，但不要求验证码
    elif captcha_check["required"]:
        # 正常流程：需要验证码
        if not request.captcha_id or not request.captcha_code:
            # ...
```

### 4.3 方案三：使用会话Token（更安全）

**生成会话Token**：

```python
# 验证成功后，生成会话Token
import secrets

_session_tokens = {}  # {token: {device_id, card_key, expire_at}}

def create_session_token(device_id: str, card_key: str) -> str:
    token = secrets.token_urlsafe(32)
    _session_tokens[token] = {
        "device_id": device_id,
        "card_key": card_key,
        "expire_at": datetime.now() + timedelta(days=30)
    }
    return token

def verify_session_token(token: str) -> tuple[bool, str]:
    """验证会话Token，返回 (有效, card_key)"""
    if token not in _session_tokens:
        return False, ""
    
    session = _session_tokens[token]
    if datetime.now() > session["expire_at"]:
        del _session_tokens[token]
        return False, ""
    
    return True, session["card_key"]
```

**验证接口修改**：

```python
class ValidateRequest(BaseModel):
    card_key: Optional[str] = None
    device_id: Optional[str] = None
    session_token: Optional[str] = None  # 新增：会话Token
    captcha_id: Optional[str] = None
    captcha_code: Optional[str] = None

@app.post("/api/validate")
async def validate_card_key(request: ValidateRequest):
    # 优先使用会话Token
    if request.session_token:
        valid, card_key = verify_session_token(request.session_token)
        if valid:
            # 会话Token有效，无需验证码，直接返回内容
            # ...
            return ValidateResponse(can_access=True, ...)
        else:
            # 会话Token无效，需要重新验证
            return ValidateResponse(can_access=False, msg="会话已过期，请重新验证")
    
    # 正常验证流程（需要检查验证码）
    # ...
```

**前端修改**：

```javascript
// 保存会话时，保存Token
function saveSession(cardKey, url, password, sessionToken) {
    const session = {
        cardKey: cardKey,
        url: url,
        password: password,
        sessionToken: sessionToken,  // 新增
        deviceId: getDeviceId(),
        expireAt: Date.now() + SESSION_EXPIRE_DAYS * 24 * 60 * 60 * 1000
    };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
}

// 自动验证时，使用Token
async function checkSession() {
    const session = getLocalSession();
    
    if (session && session.sessionToken) {
        // 使用会话Token验证（无需验证码）
        const response = await fetch('/api/validate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                session_token: session.sessionToken 
            }),
        });
        // ...
    }
}
```

---

## 五、推荐方案

### 综合方案：方案一 + 方案三

```
┌─────────────────────────────────────────────────────────────────────┐
│                        推荐的验证码触发逻辑                          │
│                                                                     │
│   用户访问验证页面                                                   │
│        │                                                            │
│        ▼                                                            │
│   ┌────────────────────────────────────┐                           │
│   │ 是否有有效的会话Token？             │                           │
│   └────────────────────────────────────┘                           │
│        │                                                            │
│        ├── 有 ──────────────────────▶ 跳过验证码，直接验证Token     │
│        │                                   │                        │
│        │                                   ├── Token有效 → 直接访问  │
│        │                                   └── Token无效 → 继续下面  │
│        │                                                            │
│        └── 无 ──────────────────────▶ 检查是否需要验证码            │
│                                              │                      │
│                                              ├── 不需要 → 验证卡密  │
│                                              └── 需要 → 显示验证码  │
│                                                                     │
│   验证成功后：                                                       │
│   1. 生成会话Token（30天有效）                                       │
│   2. 记录设备验证成功时间                                            │
│   3. 返回内容 + Token                                                │
│                                                                     │
│   用户下次访问：                                                     │
│   1. 使用Token自动验证                                               │
│   2. 无需验证码                                                      │
│   3. 用户体验流畅                                                    │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 六、最终答案

### Q: 用户登录后关闭浏览器，下次再打开会跳出验证码吗？

**采用推荐方案后的答案：**

| 场景 | 是否显示验证码 | 说明 |
|------|----------------|------|
| 用户已登录，关闭浏览器后再打开（30天内） | ❌ 不显示 | 使用会话Token自动验证 |
| 用户已登录，关闭浏览器后再打开（30天后） | ✅ 显示 | 会话Token过期 |
| 用户首次访问 | ❌ 不显示 | 首次访问无需验证码 |
| 用户第2次失败后再次验证 | ✅ 显示 | 连续失败触发验证码 |
| 用户验证成功后立即再次验证 | ❌ 不显示 | 有成功记录，跳过验证码 |

### 实现要点

```python
# 核心逻辑：检查是否需要验证码
def should_show_captcha(device_id: str, card_key: str) -> dict:
    # 1. 如果有会话Token，跳过验证码
    # 2. 如果24小时内验证成功过，跳过验证码
    # 3. 如果设备验证次数 < 3，跳过验证码
    # 4. 如果失败次数 < 2，跳过验证码
    # 5. 其他情况，显示验证码
```

---

## 七、总结

### 关键设计原则

1. **已登录用户不受影响**：有会话Token的用户无需验证码
2. **首次访问友好**：新用户首次验证无需验证码
3. **失败后才触发**：连续失败才需要验证码
4. **防止暴力破解**：攻击者无法绕过验证码
5. **会话有效期**：30天有效期，平衡安全与体验

### 实现复杂度

| 方案 | 复杂度 | 工作量 |
|------|--------|--------|
| 方案一：记录成功时间 | ⭐⭐ | 0.5小时 |
| 方案二：前端跳过参数 | ⭐⭐ | 0.5小时 |
| 方案三：会话Token | ⭐⭐⭐ | 1小时 |
| **推荐方案（一+三）** | ⭐⭐⭐ | **1.5小时** |

---

*文档版本：1.0*
*创建时间：2026-03-28*
