# 生产环境数据库连接问题排查经验

## 问题概述

**现象**：生产环境部署后，管理后台数据为空，无法连接 PostgreSQL 数据库

**发生时间**：2026年3月15日

**影响范围**：生产环境无法正常使用

---

## 根本原因

### 1. 直接原因

`.env.local` 文件被提交到 Git 代码仓库，该文件包含：

```env
# 强制使用本地 SQLite 数据库
LOCAL_DEV_MODE=true
```

### 2. 代码逻辑问题

`src/main.py` 中的环境变量加载逻辑（修复前）：

```python
# ❌ 问题代码
_env_local = os.path.join(_parent_dir, '.env.local')
if os.path.exists(_env_local):
    load_dotenv(_env_local, override=True)  # override=True 会覆盖系统环境变量
```

### 3. 问题链路

```
.env.local 提交到仓库
    ↓
生产环境部署时包含该文件
    ↓
load_dotenv(override=True) 用 LOCAL_DEV_MODE=true 覆盖系统环境变量
    ↓
代码判断 LOCAL_DEV_MODE=true → 强制使用 SQLite
    ↓
生产环境无法连接 PostgreSQL 数据库
```

---

## 解决方案

### 1. 紧急修复（已完成）

从代码仓库删除 `.env.local` 文件：

```bash
git rm .env.local
git commit -m "fix: 移除 .env.local 文件"
```

### 2. 代码层面预防（已完成）

修改 `src/main.py` 中的环境变量加载逻辑，**防止本地配置覆盖生产环境变量**：

```python
# ✅ 安全的加载逻辑
from dotenv import load_dotenv
_env_local = os.path.join(_parent_dir, '.env.local')

# 检查是否已有生产环境数据库配置
_has_production_db = bool(
    os.getenv('DATABASE_URL') or 
    os.getenv('PGDATABASE_URL') or 
    os.getenv('COZE_SUPABASE_URL')
)

if _has_production_db:
    # 生产环境：不加载 .env.local，避免覆盖系统环境变量
    print(f"[ENV] Production database config detected, skipping .env.local")
    print(f"[ENV] DATABASE_URL = {'已设置' if os.getenv('DATABASE_URL') or os.getenv('PGDATABASE_URL') else '未设置'}")
    print(f"[ENV] COZE_SUPABASE_URL = {'已设置' if os.getenv('COZE_SUPABASE_URL') else '未设置'}")
elif os.path.exists(_env_local):
    # 本地开发：加载 .env.local（设置 LOCAL_DEV_MODE=true 使用 SQLite）
    load_dotenv(_env_local, override=True)
    print(f"[ENV] Loaded .env.local from {_env_local} (local dev mode)")
    print(f"[ENV] LOCAL_DEV_MODE = {os.getenv('LOCAL_DEV_MODE')}")
else:
    # 无任何配置
    print(f"[ENV] No .env.local and no production config, using defaults")
```

### 3. 关键改动说明

| 改动点 | 修复前 | 修复后 |
|--------|--------|--------|
| 加载条件 | 文件存在就加载 | **先检查生产环境变量，有则跳过** |
| override | 总是 `True` | 仅本地开发时使用 `True` |
| 日志输出 | 无环境区分 | 明确标注 `local dev mode` 或跳过原因 |

---

## 经验教训

### 1. 环境变量文件管理规范

| 文件 | 用途 | 是否提交到 Git |
|------|------|----------------|
| `.env.local` | 本地开发环境变量 | ❌ **绝不提交** |
| `.env.example` | 环境变量模板 | ✅ 提交 |
| `.env.production` | 生产环境变量 | ❌ 不提交，通过平台配置 |

### 2. 代码设计原则

```
┌─────────────────────────────────────────────────────────────┐
│                    环境变量加载优先级                         │
├─────────────────────────────────────────────────────────────┤
│  1. 系统环境变量（最高优先级，不可被覆盖）                      │
│  2. .env.local（仅本地开发，无生产配置时才加载）                │
│  3. 默认值（最低优先级）                                      │
└─────────────────────────────────────────────────────────────┘
```

### 3. 部署前检查清单

```bash
# 1. 检查是否有 .env 文件被提交
git ls-files | grep -E "\.env"

# 预期输出：只有 .env.example（如果有）
# 如果输出包含 .env.local 或其他敏感文件，需要删除

# 2. 检查 .gitignore 是否包含敏感文件
cat .gitignore | grep -E "\.env"

# 预期输出：
# .env.local
# .env.*.local
```

### 4. 调试手段

添加调试 API 帮助排查（已在代码中实现）：

```python
@app.get("/api/debug/db")
async def debug_database():
    """调试 API - 返回数据库连接状态"""
    return {
        "env_vars": {
            "LOCAL_DEV_MODE": os.getenv("LOCAL_DEV_MODE"),
            "DATABASE_URL": "已设置" if os.getenv("DATABASE_URL") else "未设置",
        },
        "db_mode": get_db_mode(),
        "checks": {
            "client_type": type(client).__name__,
            "query_success": True/False,
            "total_records": N
        }
    }
```

访问 `/api/debug/db` 可快速确认环境变量和数据库连接状态。

---

## 防止问题再次发生的保障措施

### 1. 代码层面（已实施）

- ✅ 生产环境检测：有 `DATABASE_URL` 时跳过 `.env.local`
- ✅ 日志增强：明确输出加载了哪个配置
- ✅ 调试 API：`/api/debug/db` 帮助快速定位问题

### 2. Git 层面（已实施）

- ✅ `.gitignore` 包含 `.env.local`
- ✅ 已从仓库删除 `.env.local`

### 3. 流程层面（建议）

- 部署前运行检查脚本：`git ls-files | grep -E "\.env"`
- 部署后查看日志确认环境变量正确
- 新成员加入时提醒环境变量管理规范

---

## 相关文件

| 文件 | 说明 |
|------|------|
| `src/main.py` | 环境变量加载逻辑（已修改） |
| `src/storage/database/db_client.py` | 数据库连接判断逻辑 |
| `.gitignore` | Git 忽略规则 |
| `.env.local` | 本地开发配置（已删除，不提交） |

---

## 修改记录

| 日期 | 文件 | 修改内容 |
|------|------|----------|
| 2026-03-15 | `.env.local` | 从 Git 仓库删除 |
| 2026-03-15 | `.coze` | 移除部署时的备份脚本，避免构建超时 |
| 2026-03-15 | `src/main.py` | 环境变量加载逻辑；修复 ValidateResponse Pydantic 验证错误；修复过期时间解析错误；添加详细验证日志 |
| 2026-03-15 | `src/storage/database/db_client.py` | 移除 `_load_env()` 调用；优先使用 DATABASE_URL |
| 2026-03-15 | `src/storage/database/postgres_client.py` | 移除 `_load_env()` 调用；添加连接超时参数 |
| 2026-03-15 | `src/storage/database/supabase_client.py` | 移除 `_load_env()` 调用 |

---

## 扩展问题：过期时间解析错误

### 问题现象

验证 API 返回 "系统错误"，日志显示：

```
验证失败堆栈: Traceback (most recent call last):
  File "main.py", line 484, in validate_card_key
    expire_time = datetime.fromisoformat(expire_at.replace('Z', '+00:00'))
```

### 根本原因

数据库返回的时间格式可能是 `2027-07-16 18:01:00+08:00`（已包含时区），而不是 ISO 格式的 `2027-07-16T18:01:00Z`。

原代码假设时间以 `Z` 结尾，但实际不是，导致 `replace()` 无效，`fromisoformat()` 解析失败。

### 解决方案

兼容不同的时间格式：

```python
# 处理不同的时间格式
if 'T' in expire_at:
    # ISO 格式: 2027-07-16T18:01:00Z
    expire_time = datetime.fromisoformat(expire_at.replace('Z', '+00:00'))
elif '+' in expire_at or expire_at.count('-') > 2:
    # 已包含时区: 2027-07-16 18:01:00+08:00
    expire_time = datetime.fromisoformat(expire_at)
else:
    # 无时区信息
    expire_time = datetime.fromisoformat(expire_at)
```

---

## 扩展问题：Pydantic 验证错误

### 问题现象

验证 API 返回 "系统错误，请稍后重试"，日志显示：

```
ERROR - 验证失败: 2 validation errors for ValidateResponse
```

### 根本原因

数据库返回的字段可能是 `None`，但 Pydantic 模型期望 `str` 类型：

```python
# 问题代码
feishu_url = card_data.get('feishu_url', '')  # 如果数据库值是 None，返回 None 而不是 ''
```

`dict.get(key, default)` 只在 key 不存在时返回默认值，如果 key 存在但值是 `None`，则返回 `None`。

### 解决方案

使用 `or` 运算符确保返回 `str` 类型：

```python
# 修复代码
feishu_url = card_data.get('feishu_url') or ''  # None or '' = ''
```

---

## 扩展问题：504 网关超时（构建阶段）

### 问题现象

部署日志显示 504 错误，服务无法启动，日志中没有任何 `[STARTUP]` 或 `[DB]` 记录。

### 根本原因

`.coze` 配置文件中，部署时的 `build` 命令包含备份脚本：

```toml
[deploy]
build = ["sh", "-c", "python scripts/backup_data.py && pip install -r requirements.txt"]
```

备份脚本 `scripts/backup_data.py` 会调用 `get_supabase_client()` 连接数据库，但：
1. 生产环境可能没有 `COZE_SUPABASE_ANON_KEY`
2. 数据库连接可能超时

导致构建阶段就卡住，服务无法启动。

### 解决方案

修改 `.coze` 配置，移除备份脚本：

```toml
[deploy]
build = ["pip", "install", "-r", "requirements.txt"]
run = ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "5000"]
```

### 教训

1. **构建命令不应包含网络操作** - 构建阶段只安装依赖，不连接数据库
2. **备份脚本应在服务启动后执行** - 通过定时任务或手动触发

---

## 扩展问题：504 网关超时（请求阶段）

### 问题现象

前端验证卡密时返回 **504 Gateway Timeout** 错误。

### 根本原因

`_load_env()` 函数中的 `coze_workload_identity` 调用在生产环境耗时过长，导致请求超时。

```python
# 问题代码
def _load_env() -> None:
    try:
        from coze_workload_identity import Client as WorkloadClient
        client = WorkloadClient()  # 可能耗时很长
        env_vars = client.get_project_env_vars()
        ...
```

### 解决方案

移除所有 `_load_env()` 调用，环境变量应在 `main.py` 启动时一次性加载：

```python
# db_client.py, postgres_client.py, supabase_client.py
def get_database_url() -> Optional[str]:
    # 不再调用 _load_env()
    return os.getenv("DATABASE_URL") or os.getenv("PGDATABASE_URL")
```

### 数据库选择优先级调整

修改前：
1. `COZE_SUPABASE_URL` 存在 → Supabase
2. `DATABASE_URL` 存在 → PostgreSQL

修改后：
1. `DATABASE_URL` 存在 → PostgreSQL 直连（优先，更可靠）
2. `COZE_SUPABASE_URL` + `COZE_SUPABASE_ANON_KEY` 存在 → Supabase

原因：
- Supabase SDK 需要完整的 URL 和 ANON_KEY
- PostgreSQL 直连更简单可靠，不依赖额外的 SDK

---

## 扩展问题：管理后台登录后循环跳转

### 问题现象

管理后台登录成功后，页面一直在"登录页面"和"主内容"之间循环跳转，无法正常使用。

### 根本原因分析

1. **Cookie 设置问题**：
   - 生产环境的 cookie 设置可能因为域名、HTTPS 等因素失败
   - 登录成功后，`check-auth` 接口返回 `authenticated: false`
   - 前端检测到未认证，重新显示登录页面

2. **认证检查流程问题**：
   - 登录成功后立即调用 `check-auth` 检查认证状态
   - 如果 `check-auth` 失败，会触发 `showLogin()`
   - 导致循环跳转

### 解决方案：Token + Authorization Header 双重认证

#### 1. 后端支持两种认证方式

后端中间件已经支持从两个地方获取 token：

```python
# 从 Authorization header 获取
auth_header = request.headers.get("Authorization", "")
if auth_header.startswith("Bearer "):
    token = auth_header[7:]

# 从 cookie 获取
if not token:
    token = request.cookies.get("admin_token")
```

#### 2. 前端实现 Token 存储和自动附加

```javascript
// Token 管理
const TOKEN_KEY = 'admin_token';

function getStoredToken() {
    return localStorage.getItem(TOKEN_KEY);
}

function setStoredToken(token) {
    localStorage.setItem(TOKEN_KEY, token);
}

// 保存原始 fetch 函数
const originalFetch = window.fetch.bind(window);

// 重写 fetch 函数，自动添加 Authorization header
window.fetch = async function(url, options = {}) {
    const token = getStoredToken();
    const headers = options.headers || {};
    
    // 如果有 token 且请求的是 API 路径，添加 Authorization header
    if (token && typeof url === 'string' && url.startsWith('/api/')) {
        headers['Authorization'] = `Bearer ${token}`;
    }
    
    return originalFetch(url, {
        ...options,
        headers,
        credentials: options.credentials || 'include'
    });
};
```

#### 3. 登录流程优化

```javascript
async function handleLogin(event) {
    const response = await fetch('/api/admin/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: password }),
    });
    
    const data = await response.json();
    
    if (data.success) {
        // 存储 token（如果有返回）
        if (data.token) {
            setStoredToken(data.token);
        }
        
        // 检查认证状态
        const authCheck = await fetch('/api/admin/check-auth');
        const authData = await authCheck.json();
        
        if (authData.authenticated) {
            showMainContent();
        } else {
            clearStoredToken();
            showError('登录状态异常，请重试');
        }
    }
}
```

### 关键改进点

| 改动点 | 修复前 | 修复后 |
|--------|--------|--------|
| Token 存储 | 仅 cookie | **cookie + localStorage** |
| Token 发送 | 自动发送 cookie | **自动附加 Authorization header** |
| 认证检查 | 单一 cookie | **header 优先，cookie 备用** |
| 失败处理 | 直接跳转登录页 | **清除 token 后显示错误** |

### 教训

1. **不要完全依赖 cookie** - localStorage 可以作为备选方案
2. **双重认证机制更可靠** - header 和 cookie 两种方式互为备份
3. **fetch 拦截器更优雅** - 无需修改每个 API 调用
4. **错误信息要明确** - 区分"密码错误"和"登录状态异常"

---

## 扩展问题：数据丢失（LOCAL_DEV_MODE 优先级问题）

### 问题现象

用户在生产环境添加的卡密数据（link_name、feishu_url）在部署后丢失。

### 根本原因

**系统环境变量 `LOCAL_DEV_MODE=true` 的优先级过高，导致生产环境错误地使用 SQLite 数据库。**

#### 问题链路

```
系统环境变量 LOCAL_DEV_MODE=true（优先级最高）
    ↓
每次部署/重启 → 使用 SQLite（/tmp/card_key_local.db）
    ↓
用户添加数据 → 保存到 SQLite
    ↓
下次部署/重启 → /tmp 目录清空 → 数据丢失
    ↓
修复后 → 连接到 PostgreSQL（正确的数据库）
    ↓
但 PostgreSQL 中从未有过这些数据
```

#### 原代码逻辑（有问题）

```python
# db_client.py
def is_local_dev_mode() -> bool:
    """判断是否为本地开发模式"""
    local_dev = os.getenv("LOCAL_DEV_MODE", "").lower()
    return local_dev in ("true", "1", "yes")  # 最高优先级，无视 DATABASE_URL
```

### 解决方案

修改数据库选择逻辑，**当有生产数据库配置时，忽略 LOCAL_DEV_MODE**：

```python
# db_client.py
def is_local_dev_mode() -> bool:
    """判断是否为本地开发模式
    
    优先级（从高到低）：
    1. 如果有 DATABASE_URL 或 COZE_SUPABASE_URL，忽略 LOCAL_DEV_MODE（强制生产模式）
    2. LOCAL_DEV_MODE=true → 本地模式
    3. 默认 → 生产模式（如果有数据库配置）或本地模式（无配置）
    """
    # 如果有生产数据库配置，忽略 LOCAL_DEV_MODE
    has_production_db = bool(
        os.getenv("DATABASE_URL") or 
        os.getenv("PGDATABASE_URL") or 
        os.getenv("COZE_SUPABASE_URL")
    )
    if has_production_db:
        return False  # 强制生产模式
    
    # 否则检查 LOCAL_DEV_MODE 环境变量
    local_dev = os.getenv("LOCAL_DEV_MODE", "").lower()
    return local_dev in ("true", "1", "yes")
```

### 关键改动说明

| 改动点 | 修复前 | 修复后 |
|--------|--------|--------|
| LOCAL_DEV_MODE 优先级 | 最高（无视其他配置） | **低于 DATABASE_URL** |
| 数据库选择逻辑 | LOCAL_DEV_MODE=true → SQLite | 有 DATABASE_URL → PostgreSQL |
| 数据安全 | 部署时丢失 | **持久化到 PostgreSQL** |

### 教训

1. **环境变量优先级要合理** - 生产数据库配置应该优先于本地开发标志
2. **临时目录数据不持久** - `/tmp` 目录在部署时会清空，不能存储重要数据
3. **日志监控很重要** - 应该监控数据库连接类型，及时发现异常
4. **部署后验证** - 部署后应检查数据库连接是否正确
