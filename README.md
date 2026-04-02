# 卡密验证系统

一个基于 FastAPI + Supabase 的卡密验证系统，支持 Vercel Serverless 和阿里云 FC 双区域部署。

## 功能

- ✅ 卡密验证
- ✅ 管理后台
- ✅ 飞书多维表格嵌入
- ✅ 设备绑定
- ✅ 过期管理
- ✅ 验证码保护

## 技术栈

| 组件 | 技术 |
|------|------|
| 后端框架 | FastAPI |
| 数据库 | Supabase PostgreSQL |
| 部署平台 | Vercel (海外) / 阿里云 FC (国内) |
| 运行时 | Python 3.12 |

## 代码仓库

| 平台 | 地址 | 用途 |
|------|------|------|
| GitHub | https://github.com/qjm150-afk/card-key-system | 主仓库，CI/CD |
| Gitee | https://gitee.com/julienqjm/card-key-system | 国内备份 |

## 快速开始

### 1. 环境准备

复制环境变量模板：
```bash
cp .env.example .env
```

编辑 `.env` 文件：
```bash
DATABASE_URL=postgresql://postgres.[项目ID]:[密码]@aws-1-[区域].pooler.supabase.com:6543/postgres
COZE_SUPABASE_URL=https://your-project.supabase.co
COZE_SUPABASE_ANON_KEY=your-anon-key
ADMIN_PASSWORD=your-password
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 运行服务

```bash
python -m uvicorn src.main:app --host 0.0.0.0 --port 5000
```

### 4. 访问

- 用户页面：http://localhost:5000/
- 管理后台：http://localhost:5000/admin

## 部署方式

### Vercel（海外访问）

详见：[Vercel + Supabase 部署指南](docs/deploy/vercel-supabase-deploy.md)

```bash
# 1. 安装 Vercel CLI
npm i -g vercel

# 2. 登录
vercel login

# 3. 部署
vercel --prod
```

### 阿里云 FC（国内访问）

✅ **已部署成功**

- API 地址: `https://card-key-api-tqnnpckgbm.cn-hangzhou.fcapp.run`
- 限制: 默认域名会下载 HTML，需绑定自定义域名

详见：[阿里云 FC 部署指南](docs/deploy/aliyun-fc-deploy.md)

### Docker

```bash
# 构建镜像
docker build -t card-key-api .

# 运行容器
docker run -p 5000:5000 \
  -e DATABASE_URL=postgresql://... \
  -e COZE_SUPABASE_URL=https://... \
  -e COZE_SUPABASE_ANON_KEY=... \
  -e ADMIN_PASSWORD=... \
  card-key-api
```

## 目录结构

```
├── api/
│   └── index.py       # Vercel 入口
├── src/
│   ├── main.py        # FastAPI 主应用
│   ├── captcha.py     # 验证码模块
│   ├── static/        # 静态文件
│   └── storage/       # 数据库配置
├── scripts/           # 工具脚本
├── docs/
│   ├── deploy/        # 部署文档
│   ├── migration/     # 迁移文档
│   └── experience/    # 经验记录
├── vercel.json        # Vercel 配置
├── Dockerfile         # Docker 构建文件
├── requirements.txt   # Python 依赖
└── .env.example       # 环境变量模板
```

## 文档导航

### 部署相关

- [Vercel + Supabase 部署指南](docs/deploy/vercel-supabase-deploy.md)
- [配置快速参考](docs/deploy/QUICK_REFERENCE.md)
- [GitHub Actions 自动部署](docs/deploy/github-actions-deploy.md)

### 迁移相关

- [迁移完成记录](docs/migration/VERCEL_MIGRATION_COMPLETE.md)
- [迁移检查清单](docs/migration/CHECKLIST.md)

### 问题记录

- [生产环境数据库连接问题](docs/experience/production-db-connection-issue.md)
- [夜间加载慢问题](docs/experience/night-loading-slow-issue.md)

## 成本分析

| 部署方式 | 月成本 | 备注 |
|----------|--------|------|
| Vercel + Supabase | ¥0 | 免费额度充足 |
| 阿里云 FC + Supabase | ¥0 | 函数计算免费额度 |
| 扣子托管 | ¥10 | 已迁移 |

## License

MIT
