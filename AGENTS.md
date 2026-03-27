# AGENTS.md - 项目开发指南

> 本文档帮助 AI 快速理解项目全貌，提高开发效率。

## 项目概览

**卡密验证系统** - 用户输入卡密后访问飞书多维表格内容，包含管理后台。

### 技术栈
- **后端**: FastAPI (Python 3.11+)
- **数据库**: PostgreSQL (Supabase)
- **前端**: HTML + Tailwind CSS (CDN) + Vanilla JS
- **认证**: Token-based (内存存储)

### 核心功能模块
1. **卡密验证** (`/api/validate`) - 用户验证卡密，获取飞书嵌入链接
2. **设备绑定** - 每卡密最多绑定5台设备
3. **管理后台** (`/admin`) - 卡种管理、卡密管理、数据统计
4. **API限流** - 防暴力破解保护

## 项目结构

```
/workspace/projects/
├── src/
│   ├── main.py                    # 主入口（所有 API 和静态页面）
│   ├── static/                    # 静态文件
│   │   ├── index.html             # 前端验证页面
│   │   └── admin.html             # 管理后台页面
│   └── storage/database/          # 数据库模块
│       ├── db_client.py           # 数据库客户端工厂
│       ├── supabase_client.py     # Supabase 客户端
│       └── postgres_client.py     # PostgreSQL 客户端
├── tests/                         # 单元测试
│   ├── test_utils.py              # 工具函数测试
│   ├── test_validate.py           # 验证 API 测试
│   ├── test_rate_limit.py         # 限流测试
│   └── ...
├── docs/                          # 项目文档
├── scripts/                       # 辅助脚本
├── pytest.ini                     # 测试配置
└── requirements.txt               # Python 依赖
```

## 快速定位代码

### 关键 API 端点 (src/main.py)
| 行号范围 | 功能 |
|---------|------|
| ~250-320 | RateLimitMiddleware 限流中间件 |
| ~350-400 | AdminAuthMiddleware 权限中间件 |
| ~1000-1200 | `/api/validate` 卡密验证 API |
| ~1600-1700 | `/api/admin/card-types` 卡种管理 |
| ~3000-3200 | `/api/admin/cards` 卡密管理 |
| ~4700-5100 | 卡密 CRUD 操作 |

### 核心工具函数 (src/main.py)
- `parse_datetime()` - 时间解析（支持多种格式）
- `calculate_is_expired()` - 过期判断
- `generate_card_key()` - 卡密生成
- `add_feishu_embed_params()` - 飞书链接处理

## 开发规范

### 时间处理 [CRITICAL]
- **存储格式**: ISO 8601 +08:00 时区
- **比较方式**: `datetime.now(BEIJING_TZ)`
- **解析函数**: 统一使用 `parse_datetime()`
- **前端处理**: 直接发送用户输入，不转 ISO

### 数据合规
- ✅ 不收集 IP 地址
- ✅ 不收集 User-Agent
- ✅ 不收集设备指纹
- 仅记录访问时间用于审计

### 限流规则
| 端点 | 限制 | 说明 |
|------|------|------|
| `/api/validate` | 10次/分钟 | 使用 card_key 前8位作为标识，不收集 IP |
| `/api/admin/login` | 5次失败后锁定15分钟 | 使用全局计数器，不收集 IP |

### 登录安全
| 配置项 | 值 |
|--------|-----|
| 最大失败次数 | 5 次 |
| 锁定时长 | 15 分钟 |
| 失败计数窗口 | 5 分钟 |

## 测试命令

```bash
# 运行所有测试
python -m pytest tests/ -v

# 运行特定测试
python -m pytest tests/test_rate_limit.py -v

# 类型检查
npx tsc --noEmit  # (如果有 TypeScript)
```

## 常见问题修复

### 筛选选项不显示
- **原因**: `relative_expired` 或 `date_expired` 变量未初始化
- **位置**: `get_filter_options()` 函数
- **修复**: 在统计循环前初始化变量

### 时间偏移 8 小时
- **原因**: 前端使用 `toISOString()` 转换
- **修复**: 直接发送用户输入的时间字符串

### NameError 回归
- **预防**: 新增变量时确保初始化
- **测试**: `test_filter_options.py` 已覆盖

## 数据库表结构

### card_types (卡种表)
- id, name, status, sort_order
- feishu_bitable_embed_url, preview_image, preview_enabled

### card_keys_table (卡密表)
- id, key_value, card_type_id
- status (1=有效, 0=停用)
- sale_status (sold/unsold/refunded/disputed)
- expire_at (固定过期时间)
- expire_after_days (相对过期天数)
- activated_at (首次激活时间)
- devices (已绑定设备 JSON)

### access_logs (访问日志表)
- id, key_value, success, msg
- device_id, created_at

## 部署

```bash
# 开发环境
coze dev

# 生产构建
coze build && coze start
```

端口: 5000 (必须)

---

*最后更新: 2026-03-27*
