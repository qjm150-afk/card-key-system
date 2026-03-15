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

`src/main.py` 中的环境变量加载逻辑：

```python
_env_local = os.path.join(_parent_dir, '.env.local')
if os.path.exists(_env_local):
    load_dotenv(_env_local, override=True)  # ⚠️ override=True 会覆盖系统环境变量
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

1. **从代码仓库删除 `.env.local` 文件**
   ```bash
   git rm .env.local
   git commit -m "fix: 移除 .env.local 文件"
   ```

2. **确保 `.gitignore` 包含该文件**
   ```
   .env.local
   ```

---

## 经验教训

### 1. 环境变量文件管理规范

| 文件 | 用途 | 是否提交到 Git |
|------|------|----------------|
| `.env.local` | 本地开发环境变量 | ❌ **绝不提交** |
| `.env.example` | 环境变量模板 | ✅ 提交 |
| `.env.production` | 生产环境变量 | ❌ 不提交，通过平台配置 |

### 2. 代码层面预防措施

#### 方案 A：禁止 override（推荐）

```python
# ❌ 错误：会覆盖系统环境变量
load_dotenv(_env_local, override=True)

# ✅ 正确：只补充缺失的环境变量
load_dotenv(_env_local, override=False)
```

#### 方案 B：生产环境跳过本地配置文件

```python
# 只在本地开发时加载 .env.local
if os.getenv('LOCAL_DEV_MODE') is None and os.path.exists(_env_local):
    load_dotenv(_env_local, override=True)
```

#### 方案 C：使用环境判断

```python
# 生产环境不加载本地配置
if not os.getenv('DATABASE_URL') and not os.getenv('COZE_SUPABASE_URL'):
    # 只有在没有生产数据库配置时才加载本地配置
    if os.path.exists(_env_local):
        load_dotenv(_env_local)
```

### 3. 部署前检查清单

- [ ] 检查 `.gitignore` 是否包含所有敏感文件
- [ ] 检查是否有 `.env.*` 文件被意外提交
- [ ] 使用 `git ls-files | grep -E "\.env"` 验证
- [ ] 部署后检查日志确认环境变量正确

### 4. 调试手段

添加调试 API 帮助排查：

```python
@app.get("/api/debug/db")
async def debug_database():
    return {
        "env_vars": {
            "LOCAL_DEV_MODE": os.getenv("LOCAL_DEV_MODE"),
            "DATABASE_URL": "已设置" if os.getenv("DATABASE_URL") else "未设置",
        },
        "db_mode": get_db_mode(),
        "checks": {...}
    }
```

---

## 相关文件

- `.gitignore` - Git 忽略规则
- `src/main.py` - 环境变量加载逻辑
- `src/storage/database/db_client.py` - 数据库连接判断逻辑

---

## 修改记录

| 日期 | 版本 | 修改内容 |
|------|------|----------|
| 2026-03-15 | fed9d78 | 删除 `.env.local` 文件，修复生产环境数据库连接问题 |
