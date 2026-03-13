# 卡密验证系统

> 一个安全、合规的卡密验证管理系统，支持飞书多维表格内容嵌入

## 项目概述

本系统是一个卡密验证管理系统，用户在前端输入卡密验证后，可访问对应的飞书文档内容。系统包含前端验证页面和管理后台两部分，采用纯 FastAPI 后端 + 静态前端架构，不依赖任何 AI 服务，确保会员过期后仍能稳定运行。

### 核心功能

- **卡密验证**：用户输入卡密后访问飞书内容
- **设备绑定**：每个卡密最多绑定5台设备
- **管理后台**：完整的卡密管理、统计分析、数据导入导出功能
- **合规设计**：不收集IP、UA等个人信息

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | FastAPI |
| 数据库 | SQLite (本地) / Supabase (云端) |
| 前端 | HTML + CSS + JavaScript |
| 样式 | Tailwind CSS (CDN) |

## 项目结构

```
.
├── src/
│   ├── main.py                    # FastAPI 主入口
│   ├── static/                    # 静态文件目录
│   │   ├── index.html             # 前端验证页面
│   │   ├── admin.html             # 管理后台页面
│   │   └── *.png/jpg              # 图标资源
│   ├── migrations/                # 数据库迁移脚本
│   │   ├── 001_add_analytics_fields.sql
│   │   ├── 002_add_link_name.sql
│   │   └── 003_add_session_id.sql
│   └── storage/database/          # 数据库模块
│       ├── db_client.py           # 数据库客户端
│       ├── supabase_client.py     # Supabase 客户端
│       └── model.py               # 数据模型定义
├── scripts/                       # 辅助脚本
│   ├── backup_data.py             # 数据备份脚本
│   ├── restore_data.py            # 数据恢复脚本
│   └── deploy.sh                  # 部署脚本
├── docs/                          # 项目文档
│   ├── 开发计划.md
│   ├── 开发规范.md
│   ├── 后台管理说明书.md
│   ├── 合规风险检查.md
│   └── DEPLOYMENT_CHECKLIST.md
└── .coze                          # Coze 配置文件
```

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 24+ (Coze CLI)

### 本地开发

```bash
# 1. 初始化项目
coze init ${COZE_WORKSPACE_PATH} --template nextjs

# 2. 启动开发服务
coze dev

# 3. 访问页面
# 前端验证页: http://localhost:5000/
# 管理后台: http://localhost:5000/admin
```

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `ADMIN_PASSWORD` | 管理员密码 | `QJM150` |
| `COZE_SUPABASE_URL` | Supabase URL (可选) | - |
| `COZE_SUPABASE_KEY` | Supabase Key (可选) | - |

## API 接口

### 用户接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/verify` | POST | 卡密验证 |
| `/api/online` | GET | 在线用户统计 |
| `/api/report/session` | POST | 会话数据上报 |

### 管理接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/admin/login` | POST | 管理员登录 |
| `/api/admin/cards` | GET | 获取卡密列表 |
| `/api/admin/cards` | POST | 创建卡密 |
| `/api/admin/cards/batch` | POST | 批量生成卡密 |
| `/api/admin/statistics/*` | GET | 统计数据接口 |
| `/api/admin/export/*` | GET | 数据导出接口 |

完整 API 文档请参考 `docs/后台管理说明书.md`

## 数据库迁移

本项目使用 SQL 迁移脚本管理数据库变更：

```bash
# 本地 SQLite 迁移
sqlite3 /tmp/card_key_test.db < src/migrations/001_add_analytics_fields.sql

# Supabase 云端迁移
# 请在 Supabase 控制台 SQL Editor 中执行迁移脚本
```

## 数据备份与恢复

```bash
# 备份数据
python scripts/backup_data.py

# 恢复数据
python scripts/restore_data.py --file backups/backup_YYYYMMDD_HHMMSS.json
```

## 部署

请参考 `docs/DEPLOYMENT_CHECKLIST.md` 完成部署前检查。

```bash
# 构建
coze build

# 启动生产服务
coze start
```

## 合规说明

本项目严格遵循《个人信息保护法》《网络安全法》等法律法规：

- ✅ 不收集 IP 地址
- ✅ 不收集 User-Agent
- ✅ 不收集设备指纹
- ✅ 仅记录必要的访问时间用于安全审计

详细合规检查清单请参考 `docs/合规风险检查.md`

## 文档索引

| 文档 | 说明 |
|------|------|
| [开发计划](docs/开发计划.md) | 功能规划与进度追踪 |
| [开发规范](docs/开发规范.md) | 开发约束与数据合规要求 |
| [后台管理说明书](docs/后台管理说明书.md) | 管理后台使用指南 |
| [合规风险检查](docs/合规风险检查.md) | 法律合规自查清单 |
| [部署检查清单](docs/DEPLOYMENT_CHECKLIST.md) | 部署前必检项目 |

## 许可证

MIT License

---

*最后更新：2026-03-14*
