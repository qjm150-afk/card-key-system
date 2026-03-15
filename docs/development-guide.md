# 卡密验证系统开发规范与经验

## 环境隔离规范

### 1. 数据库环境区分

| 环境 | 域名特征 | 数据库 | 说明 |
|-----|---------|-------|------|
| 沙箱环境 | `*.dev.coze.site` | SQLite (`/tmp/card_key_local.db`) | 测试环境，数据隔离 |
| 线上环境 | 自定义域名 (如 `kaikaixuezhang.coze.site`) | Supabase 云端数据库 | 生产环境，真实数据 |

### 2. 环境变量控制

```
沙箱环境：LOCAL_DEV_MODE=true → 使用 SQLite
线上环境：LOCAL_DEV_MODE 未设置 → 使用 Supabase
```

**判断逻辑**（见 `src/storage/database/db_client.py`）：
```python
def is_production() -> bool:
    # 本地开发模式优先级最高
    if is_local_dev_mode():  # LOCAL_DEV_MODE=true
        return False
    
    # 有 Supabase URL 且未设置本地模式，则为生产环境
    return bool(os.getenv("COZE_SUPABASE_URL"))
```

### 3. 核心原则

> **⚠️ 重要：沙箱环境操作会直接影响线上数据！**

在配置 `LOCAL_DEV_MODE=true` 之前：
- 沙箱环境和线上环境共用同一个 Supabase 数据库
- 在沙箱环境的任何数据操作（添加、删除、修改）都会同步到线上
- 测试数据会污染线上数据库

**解决方案**：`.coze` 配置文件已设置隔离：
```toml
[dev]
# 沙箱环境强制使用 SQLite
run = ["sh", "-c", "LOCAL_DEV_MODE=true python -m uvicorn src.main:app --host 0.0.0.0 --port 5000"]

[deploy]
# 线上环境使用 Supabase（无 LOCAL_DEV_MODE）
run = ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "5000"]
```

---

## 开发经验总结

### 经验1：环境隔离是测试的前提

**问题**：在沙箱环境测试批量生成功能时，10条测试数据出现在线上管理后台。

**原因**：
1. 早期配置未设置 `LOCAL_DEV_MODE=true`
2. 沙箱环境直接连接云端 Supabase
3. 数据库客户端使用全局缓存，一旦初始化不会改变

**教训**：
- 新项目初始化时，必须第一时间配置环境隔离
- 测试前确认当前数据库模式：`get_db_mode()`
- 敏感操作（批量生成、批量删除）先在测试环境验证

### 经验2：数据库客户端缓存问题

**问题**：修改 `.coze` 配置后，环境变量未立即生效。

**原因**：
```python
# db_client.py 中的全局缓存
_db_client = None
_is_sqlite = False

def get_db_client():
    global _db_client, _is_sqlite
    if _db_client is not None:  # 已缓存则直接返回
        return _db_client, _is_sqlite
    # ...
```

**教训**：
- 修改环境变量后需要重启服务才能生效
- 可通过 `reset_db_client()` 函数重置缓存（用于测试）

### 经验3：ID序号显示与数据库ID的区别

**问题**：用户看到序号22-31，以为是数据库ID。

**原因**：
```javascript
// 前端显示序号计算逻辑
const rowNumber = (currentPage - 1) * pageSize + index + 1;
```

**教训**：
- 显示序号 ≠ 数据库真实ID
- 显示序号便于用户理解（从1开始）
- 真实ID用于后端操作（编辑、删除）

---

## 最佳实践

### 1. 开发前检查清单

- [ ] 确认 `.coze` 配置中 `[dev]` 有 `LOCAL_DEV_MODE=true`
- [ ] 启动服务后检查数据库模式：调用 API 或查看日志
- [ ] 批量操作前先小范围测试（如生成1-2条）

### 2. 数据操作规范

| 操作 | 沙箱环境 | 线上环境 |
|-----|---------|---------|
| 添加卡密 | ✅ 随意测试 | ⚠️ 谨慎操作 |
| 批量生成 | ✅ 随意测试 | ⚠️ 确认参数后执行 |
| 批量删除 | ✅ 随意测试 | 🚨 先备份再删除 |
| 清空数据 | ✅ 随意测试 | 🚨 禁止操作 |

### 3. 问题排查流程

1. **数据异常**：检查是否跨环境操作
2. **环境变量不生效**：重启服务
3. **缓存问题**：调用 `reset_db_client()` 重置

---

## 更新历史

| 日期 | 更新内容 |
|-----|---------|
| 2026-03-15 | 初始版本，总结环境隔离经验 |
