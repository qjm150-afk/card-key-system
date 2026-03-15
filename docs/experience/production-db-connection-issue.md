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
| 2026-03-15 | `src/main.py` | 环境变量加载逻辑：检测生产环境配置，跳过 `.env.local` |
| 2026-03-15 | `src/storage/database/db_client.py` | 移除 `load_dotenv()` 调用，防止覆盖环境变量 |
| 2026-03-15 | `src/storage/database/postgres_client.py` | 移除 `load_dotenv()` 调用，防止覆盖环境变量 |
| 2026-03-15 | `src/storage/database/supabase_client.py` | 移除 `load_dotenv()` 调用，防止覆盖环境变量 |
