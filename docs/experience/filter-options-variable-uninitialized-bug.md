# 筛选选项不显示问题 - 变量未初始化 Bug

## 问题概述

**现象**：卡密管理后台的筛选下拉框选项丢失，固定过期日期、飞书链接等选项不显示

**发生时间**：2026年3月27日

**影响范围**：管理后台所有筛选功能（过期时间、飞书链接、卡种等）

**严重程度**：高 - 用户无法使用筛选功能，影响日常运营

---

## 问题表现

### 用户反馈截图

1. **过期时间筛选**只显示部分选项：
   - 已过期 (0条)
   - 激活后1天有效 (1条)
   - 永久有效 (2条)
   - ❌ 缺少 `2026/12/31 到期` 这个固定日期选项

2. **飞书链接筛选**缺少部分链接：
   - ❌ 缺少 `27届暑期实习` 链接选项

---

## 根本原因

### 1. 直接原因：变量未初始化

在 `/api/admin/cards/filter-options` API 中，缺少两个关键变量的初始化：

```python
# ❌ 问题代码：缺少这两个变量的初始化
# relative_expired = {}  # 激活后N天有效且已过期
# date_expired = {}      # 固定过期日期且已过期

# 后续代码使用了这些变量
if expire_time < now:
    expired_count += 1
    relative_expired[days] = relative_expired.get(days, 0) + 1  # NameError!
```

### 2. 为什么静默失败而不是报错？

```python
try:
    # ... 大量代码 ...
    relative_expired[days] = ...  # NameError: name 'relative_expired' is not defined
except Exception as e:
    logger.error(f"获取筛选选项失败: {str(e)}")
    return {"success": False, "msg": str(e)}
```

异常被 try-except 捕获，返回失败响应，前端收到空数据，筛选选项不显示。

### 3. 根因追溯：代码修改遗漏

#### 提交 `24a483f` (2026-03-27 16:20:06) 引入了问题

**修改目的**：让所有过期时间类型都保留其分组，无论是否过期

**原来的代码逻辑**：
```python
# 只有未过期的才统计到分组
if not expired:
    relative_groups[days] = ...
if not expired:
    expire_groups[date_key] = ...
```

**修改后的代码逻辑**：
```python
# 无论是否过期，都统计到分组
relative_groups[days] = ...  # 无条件统计
if expired:
    relative_expired[days] = ...  # ❌ 新增代码，但变量未初始化！

expire_groups[date_key] = ...  # 无条件统计
if expired:
    date_expired[date_key] = ...  # ❌ 新增代码，但变量未初始化！
```

#### 关键失误：同时修改两个 API，但遗漏了变量初始化

| API | 变量初始化 | 结果 |
|-----|----------|------|
| `/api/admin/expire-groups` | ✅ 正确添加了 `relative_expired = {}` 和 `date_expired = {}` | 正常工作 |
| `/api/admin/cards/filter-options` | ❌ 忘记添加这两个变量初始化 | 静默失败 |

---

## 问题链路

```
用户打开管理后台页面
    ↓
前端调用 /api/admin/cards/filter-options
    ↓
后端执行统计逻辑
    ↓
遇到 relative_expired[days] = ...
    ↓
NameError: name 'relative_expired' is not defined
    ↓
异常被 try-except 捕获
    ↓
返回 {"success": False, "msg": "..."}
    ↓
前端收到空数据
    ↓
筛选下拉框选项为空
```

---

## 解决方案

### 修复代码

在 `src/main.py` 第 3390-3391 行添加缺失的变量初始化：

```python
# 初始化统计容器
status_count = {}
sale_status_count = {}
feishu_url_groups = {}
sales_channel_count = {}
expire_groups = {}
relative_groups = {}
relative_expired = {}  # 激活后N天有效且已过期  ← 新增
date_expired = {}      # 固定过期日期且已过期      ← 新增
permanent_count = 0
expired_count = 0
card_type_count = {}
no_card_type_count = 0
```

### 提交记录

```
d32988a fix: 修复筛选选项不显示问题 - 添加缺失的变量初始化
```

---

## 经验教训

### 1. 代码同步遗漏

**问题**：两个相似逻辑的 API，修改时只在一个地方正确初始化了变量

**预防措施**：
- 修改多个相似 API 时，使用 checklist 逐项核对
- 代码审查时关注变量初始化的完整性
- 复制粘贴代码时，检查是否遗漏了变量声明

### 2. 异常被静默吞掉

**问题**：try-except 范围太大，导致变量未定义的严重错误被隐藏

**改进建议**：
```python
# ❌ 不推荐：捕获所有异常
try:
    # 大量代码
except Exception as e:
    return {"success": False, "msg": str(e)}

# ✅ 推荐：捕获特定异常，保留完整堆栈
try:
    # 具体操作
except ValueError as e:
    logger.error(f"数据格式错误: {e}")
    return {"success": False, "msg": f"数据格式错误: {e}"}
except Exception as e:
    logger.exception(f"未知错误: {e}")  # 打印完整堆栈
    raise  # 重新抛出，让调用方知道
```

### 3. 缺乏单元测试

**问题**：没有测试覆盖这种边界情况

**改进建议**：
```python
# 添加单元测试
def test_filter_options_with_expired_cards():
    """测试包含已过期卡密时的筛选选项"""
    # 准备数据：包含已过期和未过期的卡密
    # 调用 API
    # 验证返回的选项列表包含所有日期
```

### 4. 日志监控不足

**问题**：错误日志被记录但未被及时发现

**改进建议**：
- 添加告警机制：API 返回 `success: False` 时发送通知
- 定期检查错误日志

---

## 最佳实践总结

### 变量初始化检查清单

在函数/方法开始处，一次性初始化所有需要的变量：

```python
def process_data():
    # ✅ 在函数开头统一初始化所有变量
    result = {}
    count = 0
    errors = []
    processed = []
    
    # 后续代码使用这些变量
    ...
```

### Try-Except 最佳实践

```python
# ✅ 推荐：精确捕获 + 详细日志 + 不隐藏错误
async def get_filter_options():
    try:
        # 具体业务逻辑
        return {"success": True, "data": ...}
    except ValueError as e:
        logger.error(f"参数错误: {e}")
        return {"success": False, "msg": f"参数错误: {e}"}
    except Exception as e:
        logger.exception(f"获取筛选选项失败: {e}")  # 打印完整堆栈
        return {"success": False, "msg": "系统错误，请稍后重试"}
```

### 多 API 同步修改规范

当需要同步修改多个相似 API 时：

1. **列出所有需要修改的位置**
2. **逐项核对修改内容**
3. **确保所有变量初始化完整**
4. **分别测试每个 API**

---

## 相关文件

| 文件 | 说明 |
|------|------|
| `src/main.py` | 主要业务逻辑（已修复） |
| `docs/experience/` | 经验文档目录 |

---

## 相关提交

| 提交 | 时间 | 说明 |
|------|------|------|
| `24a483f` | 2026-03-27 16:20 | 引入问题：修改逻辑时遗漏变量初始化 |
| `8cea437` | 2026-03-27 16:34 | 修复判断条件，但未发现变量未初始化问题 |
| `d32988a` | 2026-03-27 | 修复：添加缺失的变量初始化 |

---

## 修改记录

| 日期 | 文件 | 修改内容 |
|------|------|----------|
| 2026-03-27 | `src/main.py` | 添加 `relative_expired = {}` 和 `date_expired = {}` 变量初始化 |
| 2026-03-27 | `docs/experience/filter-options-variable-uninitialized-bug.md` | 创建本文档 |
