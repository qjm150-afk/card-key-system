# 卡密验证系统

一个基于 FastAPI + Supabase 的卡密验证系统。

## 功能

- 卡密验证
- 管理后台
- 飞书多维表格嵌入
- 设备绑定
- 过期管理

## 技术栈

- Python 3.12
- FastAPI
- Supabase (PostgreSQL)

## 快速开始

### 1. 环境准备

复制环境变量模板：
```bash
cp .env.example .env
```

编辑 `.env` 文件，填写以下配置：
```
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

## Docker 部署

```bash
# 构建镜像
docker build -t card-key-api .

# 运行容器
docker run -p 5000:5000 \
  -e COZE_SUPABASE_URL=https://your-project.supabase.co \
  -e COZE_SUPABASE_ANON_KEY=your-anon-key \
  -e ADMIN_PASSWORD=your-password \
  card-key-api
```

## 目录结构

```
├── src/              # 源代码
│   ├── main.py       # 主入口
│   ├── captcha.py    # 验证码模块
│   └── storage/      # 数据库配置
├── scripts/          # 工具脚本
├── storage/          # 存储配置
├── Dockerfile        # Docker 构建文件
├── requirements.txt  # Python 依赖
└── .env.example      # 环境变量模板
```

## License

MIT
