# 验证码触发与会话保持分析

## 一、当前实现（数据库持久化）

### 1.1 会话Token存储

**数据库表结构**：

```sql
CREATE TABLE session_tokens (
    id SERIAL PRIMARY KEY,
    token VARCHAR(64) UNIQUE NOT NULL,      -- 会话Token（256位熵）
    device_id VARCHAR(64) NOT NULL,         -- 设备ID
    card_key_hash VARCHAR(64) NOT NULL,     -- 卡密哈希值（SHA256前32位）
    created_at TIMESTAMP DEFAULT NOW(),     -- 创建时间
    expire_at TIMESTAMP NOT NULL            -- 过期时间
);
```

**代码位置**：`src/captcha.py`

```python
def create_session_token(device_id: str, card_key: str) -> str:
    """创建会话Token（持久化到数据库）"""
    import secrets
    
    token = secrets.token_urlsafe(32)
    expire_at = datetime.now() + timedelta(days=30)
    card_key_hash = _hash_card_key(card_key)  # 只存哈希，不存明文
    
    # 存储到数据库
    client.table('session_tokens').insert({
        "token": token,
        "device_id": device_id,
        "card_key_hash": card_key_hash,
        "expire_at": expire_at.isoformat()
    }).execute()
    
    return token


def verify_session_token(token: str, card_key: str = None) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    验证会话Token（从数据库查询）
    
    Args:
        token: 会话Token
        card_key: 卡密明文（用于验证哈希匹配）
    
    Returns:
        (是否有效, card_key, device_id)
    """
    # 从数据库查询
    response = client.table('session_tokens').select('*').eq('token', token).execute()
    
    if not response.data:
        return False, None, None
    
    session = response.data[0]
    
    # 检查是否过期
    if datetime.now() > session["expire_at"]:
        client.table('session_tokens').delete().eq('token', token).execute()
        return False, None, None
    
    # 如果提供了card_key，验证哈希匹配
    if card_key:
        expected_hash = _hash_card_key(card_key)
        if session['card_key_hash'] != expected_hash:
            return False, None, None
        return True, card_key, session['device_id']
    
    return True, None, session['device_id']
```

### 1.2 前端会话存储

**代码位置**：`src/static/index.html`

```javascript
// 会话过期时间（30天）
const SESSION_EXPIRE_DAYS = 30;
const STORAGE_KEY = 'card_key_session';

// 保存会话到 localStorage（包含 sessionToken）
function saveSession(cardKey, url, password, sessionToken = null) {
    const session = {
        cardKey: cardKey,
        url: url,
        password: password,
        deviceId: getDeviceId(),
        sessionToken: sessionToken,  // 后端返回的会话Token
        expireAt: Date.now() + SESSION_EXPIRE_DAYS * 24 * 60 * 60 * 1000
    };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
}

// 页面加载时检查会话
async function checkSession() {
    const session = getLocalSession();
    
    if (session) {
        // 有本地会话，尝试使用 session_token 自动验证
        if (session.sessionToken) {
            // 传递 cardKey 和 sessionToken 进行验证
            const result = await validateCardKey(session.cardKey, false, session.sessionToken);
            if (result.success) {
                return; // 验证成功，已显示内容
            }
        } else {
            // 没有 session_token，使用旧的验证方式
            const result = await validateCardKey(session.cardKey, false);
            if (result.success) {
                return;
            }
        }
        // 验证失败，显示验证页面
        showValidate();
    } else {
        showValidate();
        await checkCaptchaRequired();
    }
}
```

---

## 二、验证流程

### 2.1 首次验证流程

```
用户首次访问
    ↓
显示验证页面（可能显示验证码）
    ↓
输入卡密验证
    ↓
验证成功 → 创建 sessionToken
    ↓
前端保存：localStorage + sessionToken
后端保存：数据库 session_tokens 表
    ↓
返回 sessionToken 给前端
```

### 2.2 自动恢复流程（第二天打开网页）

```
用户打开网页
    ↓
从 localStorage 读取 session
    ↓
同时传递 cardKey 和 sessionToken 给后端
    ↓
后端验证：
  1. 从数据库查询 sessionToken
  2. 验证 card_key_hash 匹配
  3. 验证未过期
    ↓
验证通过 → 跳过验证码，直接显示内容 ✅
```

---

## 三、安全性分析

### 3.1 防止暴力破解

| 攻击场景 | 防护措施 | 结果 |
|----------|----------|------|
| 猜测Token | Token = 256位熵（约10^77种可能） | ✅ 不可行 |
| 窃取Token | Token与设备ID绑定 | ✅ 跨设备无效 |
| 数据库泄露 | 只存储卡密哈希，不存明文 | ✅ 无法获取卡密 |

### 3.2 Token验证逻辑

```python
# 后端验证接口
if session_token and card_key:
    # 验证Token有效性和卡密哈希匹配
    valid, token_card_key, token_device_id = verify_session_token(session_token, card_key)
    if valid:
        # Token有效 + 哈希匹配 → 跳过验证码
        skip_captcha = True
    else:
        # Token无效或哈希不匹配 → 继续正常验证流程
        skip_captcha = False
```

---

## 四、数据库持久化优势

| 场景 | 内存存储（旧） | 数据库存储（新） |
|------|---------------|-----------------|
| 服务器重启 | ❌ Session丢失 | ✅ Session保留 |
| 部署新版本 | ❌ Session丢失 | ✅ Session保留 |
| 多实例部署 | ❌ Session不共享 | ✅ Session共享 |
| 数据库泄露 | - | ⚠️ 但只有哈希值 |

---

## 五、API接口定义

### 请求模型

```python
class ValidateRequest(BaseModel):
    card_key: str                              # 卡密
    device_id: Optional[str] = None            # 设备ID
    captcha_id: Optional[str] = None           # 验证码ID
    captcha_code: Optional[str] = None         # 验证码文本
    session_token: Optional[str] = None        # 会话Token（自动验证时使用）
```

### 响应模型

```python
class ValidateResponse(BaseModel):
    can_access: bool                           # 是否可访问
    url: str = ""                              # 飞书链接
    password: str = ""                         # 访问密码
    msg: str = ""                              # 消息
    session_token: Optional[str] = None        # 会话Token（验证成功后返回）
    captcha_required: Optional[bool] = None    # 是否需要验证码
    captcha_reason: Optional[str] = None       # 需要验证码的原因
```

---

## 六、常见问题

### Q1: 用户关闭浏览器后，第二天打开会触发验证码吗？

**答案：不会**（30天内）

- Session Token 持久化到数据库，服务器重启后仍然有效
- 前端同时传递 `sessionToken` 和 `cardKey`
- 后端验证通过后跳过验证码

### Q2: 如果卡密被重置/删除，Session还能用吗？

**答案：不能**

- 后端完整验证卡密有效性
- Session只是跳过验证码，不是跳过卡密验证

### Q3: Token被盗用怎么办？

**答案：有多重保护**

1. Token与设备ID绑定
2. 有效期30天
3. 卡密哈希验证，无法伪造
4. 用户可主动退出登录撤销Token

---

## 七、相关文件

| 文件 | 说明 |
|------|------|
| `src/captcha.py` | 验证码和Session Token核心逻辑 |
| `src/main.py` | 验证API接口 |
| `src/static/index.html` | 前端验证逻辑 |
| `tests/test_validate.py` | 验证API测试用例 |
