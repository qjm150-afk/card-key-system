# 阿里云 FC + Supabase 精准迁移方案

## 一、现有系统分析

### 1.1 系统架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                        现有架构（扣子平台）                          │
│                                                                     │
│   用户 ───▶ 扣子平台 ───▶ FastAPI ───▶ PostgreSQL (Supabase)       │
│              │              │                                       │
│         自动注入        main.py                                     │
│         DATABASE_URL                                               │
│         COZE_SUPABASE_URL                                         │
│         COZE_SUPABASE_ANON_KEY                                    │
│                                                                     │
│   访问域名：https://xxx.dev.coze.site                              │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 技术栈

| 组件 | 现有技术 | 迁移后技术 |
|------|----------|------------|
| 后端框架 | FastAPI | FastAPI（不变） |
| 数据库 | PostgreSQL (扣子托管) | PostgreSQL (Supabase) |
| 前端 | HTML/CSS/JS | HTML/CSS/JS（不变） |
| 部署平台 | 扣子平台 | 阿里云 FC |
| 数据库连接 | 环境变量自动注入 | 环境变量手动配置 |

### 1.3 核心文件结构

```
/workspace/projects/
├── src/
│   ├── main.py                    # 主应用（核心业务逻辑）
│   ├── static/
│   │   ├── index.html            # 用户验证页面
│   │   ├── admin.html            # 管理后台
│   │   └── ...                   # 其他静态资源
│   └── storage/
│       └── database/
│           ├── db_client.py      # 数据库客户端入口
│           ├── supabase_client.py # Supabase 客户端
│           └── postgres_client.py # PostgreSQL 客户端
├── scripts/
│   └── backup_data.py            # 数据备份脚本
└── data_export_for_production.json # 已导出的数据
```

### 1.4 核心功能模块

| 模块 | 功能 | 实现位置 |
|------|------|----------|
| **用户验证** | 卡密输入、验证、设备绑定 | `src/main.py` - `/api/validate` |
| **飞书嵌入** | iframe 嵌入 + 隐藏按钮 | `src/static/index.html` |
| **管理后台** | 卡密管理、卡种管理、统计 | `src/main.py` - `/api/admin/*` |
| **访问日志** | 验证日志、行为追踪 | `src/main.py` - `log_access()` |
| **设备管理** | 设备绑定/解绑、退出登录 | `src/main.py` - `/api/logout` |

---

## 二、需要修改的部分

### 2.1 需要修改的文件（核心）

| 文件 | 修改内容 | 复杂度 |
|------|----------|--------|
| `src/storage/database/supabase_client.py` | 移除扣子平台依赖，直接使用环境变量 | ⭐⭐ |
| `src/storage/database/db_client.py` | 保持不变（已适配） | - |
| `src/main.py` | 移除扣子平台特定的 SDK 调用 | ⭐⭐⭐ |
| `s.yaml` | **新建**：阿里云 FC 部署配置 | ⭐⭐⭐ |
| `code/fc_handler.py` | **新建**：FC 入口适配器 | ⭐⭐ |
| `code/requirements.txt` | **新建**：依赖列表 | ⭐ |

### 2.2 需要新增的环境变量

```bash
# Supabase 连接信息（从 Supabase 项目设置中获取）
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

# 管理员密码
ADMIN_PASSWORD=your_password

# 对象存储（预览图功能）
COZE_BUCKET_ENDPOINT_URL=     # 可选
COZE_BUCKET_NAME=             # 可选
```

### 2.3 不需要修改的部分

| 文件/目录 | 说明 |
|-----------|------|
| `src/static/index.html` | 前端页面完全不用改 |
| `src/static/admin.html` | 管理后台完全不用改 |
| `src/storage/database/model.py` | 数据模型不变 |
| 所有业务逻辑 API | 接口逻辑不变 |

---

## 三、详细迁移步骤

### 第一步：创建 Supabase 数据库（1-2小时）

#### 1.1 注册 Supabase 账号

```
1. 访问 https://supabase.com
2. 使用 GitHub 账号登录（推荐）
3. 创建新项目：
   - Name: card-key-system
   - Database Password: 设置一个强密码
   - Region: Singapore（离中国最近）
```

#### 1.2 创建数据表

在 Supabase SQL Editor 中执行：

```sql
-- 1. 卡种表
CREATE TABLE card_types (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    preview_image TEXT,
    preview_enabled BOOLEAN DEFAULT FALSE,
    blur_level INTEGER DEFAULT 8,
    status INTEGER DEFAULT 1,
    sort_order INTEGER DEFAULT 0,
    deleted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX ix_card_types_name ON card_types(name);
CREATE INDEX ix_card_types_status ON card_types(status);

-- 2. 卡密表
CREATE TABLE card_keys_table (
    id SERIAL PRIMARY KEY,
    key_value VARCHAR(50) UNIQUE NOT NULL,
    status INTEGER DEFAULT 1,
    card_type_id INTEGER REFERENCES card_types(id),
    feishu_url TEXT,
    feishu_password VARCHAR(100),
    link_name VARCHAR(100),
    expire_at TIMESTAMP WITH TIME ZONE,
    expire_after_days INTEGER,
    activated_at TIMESTAMP WITH TIME ZONE,
    max_devices INTEGER DEFAULT 5,
    devices TEXT,
    user_note VARCHAR(200),
    sale_status VARCHAR(20) DEFAULT 'unsold',
    sales_channel VARCHAR(100),
    order_id VARCHAR(100),
    last_used_at TIMESTAMP WITH TIME ZONE,
    sys_platform VARCHAR(50) DEFAULT '卡密系统',
    bstudio_create_time TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX ix_card_keys_key_value ON card_keys_table(key_value);
CREATE INDEX ix_card_keys_status ON card_keys_table(status);
CREATE INDEX ix_card_keys_card_type_id ON card_keys_table(card_type_id);

-- 3. 访问日志表
CREATE TABLE access_logs (
    id SERIAL PRIMARY KEY,
    card_key_id INTEGER REFERENCES card_keys_table(id),
    key_value VARCHAR(50) NOT NULL,
    success BOOLEAN DEFAULT FALSE,
    error_msg VARCHAR(200),
    access_time TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    access_date DATE,
    access_hour INTEGER,
    is_first_access BOOLEAN DEFAULT FALSE,
    sales_channel VARCHAR(100),
    session_id VARCHAR(64)
);

CREATE INDEX ix_access_logs_key_value ON access_logs(key_value);
CREATE INDEX ix_access_logs_access_time ON access_logs(access_time);

-- 4. 预览图片表
CREATE TABLE preview_images (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    url TEXT NOT NULL,
    image_key TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 5. 链接健康表
CREATE TABLE link_health_table (
    id SERIAL PRIMARY KEY,
    feishu_url TEXT NOT NULL,
    link_name VARCHAR(200),
    status VARCHAR(20) DEFAULT 'unknown',
    http_code INTEGER,
    error_message VARCHAR(500),
    last_check_time TIMESTAMP WITH TIME ZONE,
    next_check_time TIMESTAMP WITH TIME ZONE,
    consecutive_failures INTEGER DEFAULT 0,
    total_checks INTEGER DEFAULT 0,
    successful_checks INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE
);

-- 6. 管理员设置表
CREATE TABLE admin_settings (
    id SERIAL PRIMARY KEY,
    key VARCHAR(100) UNIQUE NOT NULL,
    value TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE
);

-- 插入默认管理员密码
INSERT INTO admin_settings (key, value) VALUES ('admin_password', 'QJM150');

-- 7. 健康检查表
CREATE TABLE health_check (
    id INTEGER PRIMARY KEY,
    updated_at TIMESTAMP WITH TIME ZONE
);

INSERT INTO health_check (id, updated_at) VALUES (1, NOW());
```

#### 1.3 导入数据

使用备份数据导入：

```bash
# 在本地开发环境执行
cd /workspace/projects
python scripts/import_to_supabase.py
```

或手动导入 CSV（从 Supabase Dashboard）。

#### 1.4 获取连接信息

```
Supabase Dashboard → Settings → API

需要记录：
- URL: https://xxx.supabase.co
- anon public key: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

---

### 第二步：修改代码（2-3小时）

#### 2.1 修改 supabase_client.py

```python
# src/storage/database/supabase_client.py
import os
from typing import Optional
import httpx
from supabase import create_client, Client, ClientOptions

def get_supabase_credentials() -> tuple[str, str]:
    """获取 Supabase 凭证（从环境变量）"""
    # 优先使用新环境变量名
    url = os.getenv("SUPABASE_URL") or os.getenv("COZE_SUPABASE_URL")
    anon_key = os.getenv("SUPABASE_ANON_KEY") or os.getenv("COZE_SUPABASE_ANON_KEY")

    if not url:
        raise ValueError("SUPABASE_URL is not set")
    if not anon_key:
        raise ValueError("SUPABASE_ANON_KEY is not set")

    return url, anon_key


def get_supabase_client(token: Optional[str] = None) -> Client:
    """创建 Supabase 客户端"""
    url, anon_key = get_supabase_credentials()

    http_client = httpx.Client(
        timeout=httpx.Timeout(
            connect=20.0,
            read=60.0,
            write=60.0,
            pool=10.0,
        ),
        limits=httpx.Limits(
            max_connections=100,
            max_keepalive_connections=20,
            keepalive_expiry=30.0,
        ),
        http2=True,
        follow_redirects=True,
    )

    options = ClientOptions(
        httpx_client=http_client,
        auto_refresh_token=False,
    )

    return create_client(url, anon_key, options=options)
```

#### 2.2 创建 FC 入口文件

创建 `code/fc_handler.py`：

```python
"""
阿里云函数计算 FC 入口文件
适配 FastAPI 应用到 FC HTTP 触发器
"""
import json
import logging
from typing import Dict, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 导入主应用
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.main import app
from starlette.testclient import TestClient

client = TestClient(app)


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    FC HTTP 触发器入口函数
    """
    try:
        method = event.get('method', 'GET')
        path = event.get('path', '/')
        headers = event.get('headers', {})
        queries = event.get('queries', {})
        body = event.get('body', '')
        
        # 处理查询参数
        params = {}
        if queries:
            for key, value in queries.items():
                if isinstance(value, list):
                    params[key] = value[0] if value else ''
                else:
                    params[key] = value
        
        # 处理请求体
        content = None
        if body:
            if isinstance(body, str):
                content = body.encode('utf-8')
            elif isinstance(body, bytes):
                content = body
        
        logger.info(f"Request: {method} {path}")
        
        response = client.request(
            method=method,
            url=path,
            headers=dict(headers),
            params=params,
            content=content
        )
        
        # 构造 FC 响应
        response_headers = {}
        for key, value in response.headers.items():
            if key.lower() not in ('transfer-encoding', 'content-encoding', 'connection'):
                response_headers[key] = value
        
        return {
            'statusCode': response.status_code,
            'headers': response_headers,
            'body': response.text
        }
        
    except Exception as e:
        logger.error(f"Handler error: {str(e)}", exc_info=True)
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({
                'error': 'Internal Server Error',
                'message': str(e)
            }, ensure_ascii=False)
        }
```

#### 2.3 创建 FC 配置文件

创建 `s.yaml`：

```yaml
edition: 1.0.0
name: card-key-system
access: default

vars:
  region: cn-hangzhou

services:
  card-key-service:
    component: fc
    props:
      region: ${vars.region}
      service:
        name: card-key-service
        description: 卡密验证服务
        internetAccess: true
        environmentVariables:
          SUPABASE_URL: ${env(SUPABASE_URL)}
          SUPABASE_ANON_KEY: ${env(SUPABASE_ANON_KEY)}
          ADMIN_PASSWORD: ${env(ADMIN_PASSWORD)}
      
      function:
        name: card-key-function
        description: 卡密验证函数
        runtime: python3.9
        codeUri: ./
        handler: code.fc_handler.handler
        timeout: 60
        memorySize: 512
        instanceConcurrency: 10
      
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
              - PATCH
              - HEAD
              - OPTIONS
      
      customDomains:
        - domainName: auto
          protocol: HTTP
          routeConfigs:
            - path: /*
              serviceName: card-key-service
              functionName: card-key-function
```

#### 2.4 创建依赖文件

创建 `code/requirements.txt`：

```
fastapi>=0.104.0
uvicorn>=0.24.0
supabase>=2.0.0
httpx>=0.25.0
python-dotenv>=1.0.0
pydantic>=2.0.0
python-multipart>=0.0.6
starlette>=0.27.0
psycopg2-binary>=2.9.0
```

#### 2.5 移除扣子平台特定代码

在 `src/main.py` 中移除以下代码：

```python
# 删除这些导入和调用
# from coze_coding_dev_sdk.s3 import S3SyncStorage
# from coze_workload_identity import Client as WorkloadClient
```

修改预览图 URL 生成逻辑（如果有使用对象存储）：

```python
# 如果预览图存储在对象存储，需要替换为其他存储方案
# 或直接使用完整的 URL
```

---

### 第三步：本地测试（1小时）

#### 3.1 配置环境变量

创建 `.env` 文件：

```bash
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
ADMIN_PASSWORD=your_password
```

#### 3.2 本地运行

```bash
cd /workspace/projects
python -m uvicorn src.main:app --reload --port 5000
```

#### 3.3 测试接口

```bash
# 健康检查
curl http://localhost:5000/health

# 用户页面
curl http://localhost:5000/

# 管理后台
curl http://localhost:5000/admin

# 测试验证接口
curl -X POST http://localhost:5000/api/validate \
  -H "Content-Type: application/json" \
  -d '{"card_key":"CSS-01B2-4322-AB9F","device_id":"test-device"}'
```

---

### 第四步：部署到阿里云 FC（1-2小时）

#### 4.1 安装 Serverless Devs 工具

```bash
npm install -g @serverless-devs/s
s --version
```

#### 4.2 配置阿里云密钥

```bash
s config add

# 输入：
# - AccountID: 你的阿里云账号 ID
# - AccessKeyID: 你的 AccessKey ID
# - AccessKeySecret: 你的 AccessKey Secret
```

#### 4.3 设置环境变量

```bash
export SUPABASE_URL="https://xxx.supabase.co"
export SUPABASE_ANON_KEY="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
export ADMIN_PASSWORD="your_password"
```

#### 4.4 部署

```bash
cd /workspace/projects
s deploy
```

#### 4.5 验证部署

```bash
# 部署成功后会输出访问地址
# 例如：https://xxxxxx.cn-hangzhou.fc.aliyuncs.com

# 测试
curl https://your-fc-url/health
curl https://your-fc-url/
```

---

## 四、飞书嵌入功能说明

### 4.1 现有实现分析

你的系统已经实现了完整的飞书嵌入方案：

**位置**：`src/static/index.html`

**核心代码**：

```javascript
// 1. 飞书 iframe 嵌入
<iframe id="feishuFrame" class="feishu-frame" 
        sandbox="allow-scripts allow-same-origin allow-forms allow-popups">
</iframe>

// 2. 隐藏"进入原应用"按钮的方案
// 方案A：CSS 裁剪（通过 height: calc(100% + 50px) 隐藏底部按钮）
.iframe-container .feishu-frame {
    height: calc(100% + 50px);  // 将底部按钮裁剪掉
}

// 方案B：透明遮罩层（阻止点击）
<div class="feishu-bottom-mask"></div>      // 底部遮罩
<div class="feishu-top-right-mask"></div>   // 右上角遮罩
```

**嵌入参数添加**（在 `main.py` 中）：

```python
def add_feishu_embed_params(url: str) -> str:
    """
    为飞书多维表格嵌入链接添加官方参数
    - hideHeader=1: 隐藏头部
    - hideSidebar=1: 隐藏侧边栏
    - vc=true: 隐藏新增视图
    """
    embed_params = {
        'hideHeader': '1',
        'hideSidebar': '1',
        'vc': 'true',
    }
    # ... 添加参数逻辑
```

### 4.2 迁移后无需修改

飞书嵌入功能**完全不需要修改**，因为：

1. **前端代码不变**：`index.html` 的嵌入逻辑不变
2. **后端逻辑不变**：`add_feishu_embed_params()` 函数不变
3. **URL 参数不变**：飞书官方参数不变

---

## 五、注意事项

### 5.1 数据库连接

| 项目 | 扣子平台 | 阿里云 FC |
|------|----------|-----------|
| 环境变量 | 自动注入 | 手动配置 |
| 变量名 | `COZE_SUPABASE_URL` | `SUPABASE_URL` |
| 连接池 | 自动管理 | 需要配置 |

### 5.2 静态文件

| 项目 | 扣子平台 | 阿里云 FC |
|------|----------|-----------|
| 静态目录 | `/static` | `/static`（不变） |
| 文件访问 | 自动映射 | 需要配置路由 |

### 5.3 对象存储

如果你的预览图使用了扣子的对象存储：

- **选项1**：迁移到阿里云 OSS
- **选项2**：使用 Supabase Storage
- **选项3**：直接存储完整 URL

---

## 六、迁移检查清单

### 迁移前

- [ ] 备份现有数据
- [ ] 注册 Supabase 账号
- [ ] 注册阿里云账号并实名认证
- [ ] 开通函数计算 FC 服务
- [ ] 获取 Supabase URL 和 Key

### 迁移中

- [ ] 创建 Supabase 数据表
- [ ] 导入数据
- [ ] 修改代码
- [ ] 本地测试通过
- [ ] 配置阿里云密钥
- [ ] 部署到 FC

### 迁移后

- [ ] 验证用户验证页面
- [ ] 验证飞书嵌入
- [ ] 验证管理后台
- [ ] 验证卡密管理
- [ ] 验证数据统计
- [ ] 监控运行状态

---

## 七、时间预估

| 步骤 | 时间 |
|------|------|
| Supabase 数据库创建与导入 | 1-2 小时 |
| 代码修改 | 2-3 小时 |
| 本地测试 | 1 小时 |
| 部署上线 | 1-2 小时 |
| **总计** | **5-8 小时** |

---

## 八、常见问题

### Q1: 数据库连接超时？

**解决方案**：检查 Supabase 项目状态，确认网络连通性。

### Q2: 静态文件无法访问？

**解决方案**：确保 FastAPI 正确挂载静态文件目录：

```python
app.mount("/static", StaticFiles(directory="static"), name="static")
```

### Q3: 飞书嵌入不显示？

**解决方案**：
1. 检查飞书链接是否正确
2. 确认嵌入参数已添加
3. 检查浏览器控制台错误

---

*文档版本：1.0*
*创建时间：2026-03-28*
