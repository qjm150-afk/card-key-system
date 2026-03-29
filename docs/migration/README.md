# 扣子托管迁移指南

## 一、迁移概述

### 1.1 迁移原因

| 项目 | 扣子托管 | 阿里云FC + Supabase |
|------|----------|---------------------|
| 月成本 | ~470元 | ~0.33元 |
| 数据库 | 内置PostgreSQL | Supabase免费版 |
| 可控性 | 有限 | 完全控制 |
| Trace日志 | 收费 | 免费 |

### 1.2 迁移目标

- **计算平台**: 阿里云函数计算 FC
- **数据库**: Supabase PostgreSQL（免费500MB）
- **域名**: FC默认域名（免费，无需备案）

### 1.3 成本对比

| 方案 | 月成本 | 年成本 |
|------|--------|--------|
| 扣子托管（收费后） | ~470元 | ~5,640元 |
| 阿里云FC + Supabase | ~0.33元 | ~4元 |
| **节省** | - | **~5,636元/年** |

---

## 二、迁移前准备

### 2.1 关闭扣子Trace日志

根据扣子文档，Trace日志上报开关默认开启，支持关闭。

**操作步骤**：
1. 登录扣子编程平台
2. 进入项目设置
3. 找到"Trace日志上报"开关
4. 关闭开关

### 2.2 创建Supabase项目

1. 访问 https://supabase.com
2. 创建新项目
3. 记录以下信息：
   - Project URL
   - Anon Key
   - Connection String

### 2.3 创建阿里云FC服务

1. 访问 https://fc.console.aliyun.com
2. 创建服务和函数
3. 选择 Python 运行时
4. 配置环境变量

---

## 三、数据库迁移

### 3.1 数据库表结构

需要迁移的表：

| 表名 | 说明 | 预估大小 |
|------|------|----------|
| card_keys_table | 卡密表 | ~80MB（10万条） |
| card_types | 卡种表 | ~1MB |
| access_logs | 访问日志表 | ~50MB |
| session_tokens | 会话Token表 | ~1MB |
| admin_settings | 管理设置 | ~10KB |
| preview_images | 预览图片 | ~1MB |
| 其他表 | 辅助表 | ~1MB |

**总计**: 约150MB（Supabase免费版500MB足够）

### 3.2 导出数据

```bash
# 从扣子数据库导出
pg_dump -h $PGHOST -U $PGUSER -d $PGDATABASE \
  --no-owner --no-acl \
  -f backup.sql
```

### 3.3 导入到Supabase

```bash
# 导入到Supabase
psql -h db.xxxx.supabase.co -U postgres -d postgres \
  -f backup.sql
```

---

## 四、阿里云FC配置

### 4.1 目录结构

```
card-key-system/
├── src/
│   ├── main.py          # FastAPI应用入口
│   ├── captcha.py       # 验证码模块
│   └── ...
├── storage/
│   └── database/
│       └── db_client.py # 数据库客户端
├── requirements.txt
├── Dockerfile           # FC容器配置
├── s.yaml              # FC部署配置
└── .env.example        # 环境变量示例
```

### 4.2 FC配置文件 (s.yaml)

```yaml
edition: 1.0.0
name: card-key-system
access: default

vars:
  region: cn-hangzhou

services:
  card-key-api:
    component: fc
    props:
      region: ${vars.region}
      service:
        name: card-key-service
        description: 卡密验证系统
        internetAccess: true
      function:
        name: api
        description: FastAPI接口服务
        runtime: custom-container
        code: ./
        timeout: 60
        memorySize: 512
        cpu: 0.5
        instanceConcurrency: 10
        customContainerConfig:
          image: registry.cn-hangzhou.aliyuncs.com/your-repo/card-key:latest
          command: '["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "9000"]'
          port: 9000
        environmentVariables:
          DATABASE_URL: ${env.DATABASE_URL}
          SUPABASE_URL: ${env.SUPABASE_URL}
          SUPABASE_KEY: ${env.SUPABASE_KEY}
          ADMIN_PASSWORD: ${env.ADMIN_PASSWORD}
      triggers:
        - name: httpTrigger
          type: http
          config:
            authType: anonymous
            methods:
              - GET
              - POST
              - PUT
              - DELETE
      customDomains:
        - domainName: auto
          protocol: HTTP
          routeConfigs:
            - path: /*
              serviceName: card-key-service
              functionName: api
```

### 4.3 Dockerfile

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 复制代码
COPY . .

# 暴露端口
EXPOSE 9000

# 启动命令
CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "9000"]
```

### 4.4 requirements.txt 更新

```txt
# 核心框架
fastapi>=0.104.0
uvicorn>=0.24.0
pydantic>=2.0.0

# 数据库
supabase>=2.0.0
psycopg2-binary>=2.9.0

# 验证码
Pillow>=10.0.0

# 其他
python-multipart>=0.0.6
python-jose>=3.3.0
```

---

## 五、代码适配

### 5.1 数据库连接适配

创建 `storage/database/supabase_client.py`:

```python
import os
from supabase import create_client, Client

def get_supabase_client() -> Client:
    """获取Supabase客户端"""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    
    if not url or not key:
        raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set")
    
    return create_client(url, key)
```

### 5.2 环境变量配置

```bash
# .env.example
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
ADMIN_PASSWORD=your_secure_password
```

---

## 六、迁移步骤

### 步骤1：创建Supabase项目并建表

```sql
-- 在Supabase SQL编辑器中执行
-- 创建所有表结构
```

### 步骤2：导出扣子数据库数据

```bash
# 使用扣子提供的数据库连接信息导出
```

### 步骤3：导入数据到Supabase

```bash
# 导入数据
```

### 步骤4：配置阿里云FC

```bash
# 安装Serverless DevTools
npm install -g @serverless-devs/s

# 配置阿里云凭证
s config add

# 部署函数
s deploy
```

### 步骤5：测试验证

```bash
# 测试API
curl https://xxxxx.cn-hangzhou.fc.aliyuncs.com/api/validate
```

### 步骤6：切换域名

1. 确认FC服务正常
2. 切换DNS或更新用户访问地址
3. 删除扣子托管项目（停止计费）

---

## 七、注意事项

### 7.1 数据安全

- 迁移前完整备份数据
- 验证数据完整性
- 保留扣子项目直到确认迁移成功

### 7.2 服务可用性

- 建议在低峰期迁移
- 准备回滚方案
- 通知用户可能的短暂中断

### 7.3 成本监控

- 关注FC调用量
- 设置费用告警
- 定期检查Supabase存储使用量

---

## 八、迁移后检查清单

- [ ] 所有API接口正常
- [ ] 数据完整性验证
- [ ] 验证码功能正常
- [ ] 管理后台可访问
- [ ] Session Token持久化正常
- [ ] 访问日志记录正常
- [ ] 费用在预期范围内

---

## 九、回滚方案

如果迁移失败，可以：

1. 恢复扣子托管项目
2. 重新导入数据
3. 切换回原访问地址

---

## 十、参考链接

- [阿里云函数计算文档](https://help.aliyun.com/product/50980.html)
- [Supabase文档](https://supabase.com/docs)
- [Serverless DevTools](https://www.serverless-devs.com/)
