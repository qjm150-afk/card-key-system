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
- 阿里云函数计算 FC

## 部署

### 环境变量

复制 `.env.example` 为 `.env` 并填写配置：

```bash
cp .env.example .env
```

### 本地运行

```bash
pip install -r requirements.txt
python -m uvicorn src.main:app --host 0.0.0.0 --port 5000
```

### Docker 构建

```bash
docker build -t card-key-api .
docker run -p 5000:5000 card-key-api
```

## License

MIT
