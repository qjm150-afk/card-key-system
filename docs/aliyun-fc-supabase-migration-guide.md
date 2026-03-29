# 阿里云 FC + Supabase 完整迁移方案

## 一、方案概览

### 1.1 最终架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                        目标架构                                      │
│                                                                     │
│   国内用户 ──────────▶ 阿里云 FC ──────────▶ Supabase PostgreSQL    │
│                          │                      │                   │
│                    (国内节点)               (新加坡节点)             │
│                    访问延迟 <50ms           数据库延迟 100-300ms    │
│                          │                                          │
│                          ▼                                          │
│                   飞书多维表格嵌入                                   │
│                                                                     │
│   总延迟：150-350ms                                                  │
│   前3个月成本：¥0                                                    │
│   之后月成本：~¥0.33                                                 │
│   年成本：~¥4                                                        │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 组件说明

| 组件 | 作用 | 提供商 | 费用 |
|------|------|--------|------|
| 阿里云 FC | 运行 FastAPI 服务 | 阿里云 | 前3个月免费，之后 ~¥0.33/月 |
| Supabase | PostgreSQL 数据库 | Supabase | 免费（500MB） |
| FC 默认域名 | 访问入口 | 阿里云 | 免费 |
| 飞书多维表格 | 内容展示 | 飞书 | 免费 |

### 1.3 迁移时间规划

| 阶段 | 时间 | 内容 |
|------|------|------|
| 第一阶段 | 2-3 小时 | 账号注册、环境准备、数据导出 |
| 第二阶段 | 1-2 小时 | Supabase 建表、数据导入 |
| 第三阶段 | 2-3 小时 | 代码适配、本地测试 |
| 第四阶段 | 1-2 小时 | 部署上线、功能验证 |
| **总计** | **6-10 小时** | 可分 2-3 天完成 |

---

## 二、费用明细

### 2.1 阿里云 FC 费用

**试用期（前 3 个月）**：免费

**试用期后费用计算**：

| 项目 | 单价 | 你的月用量 | 月费用 |
|------|------|-----------|--------|
| 函数调用 | ¥0.0133/万次 | 6000 次 | ¥0.008 |
| 执行时长 | ¥0.00003167/GB-秒 | 2250 GB-秒 | ¥0.07 |
| 公网流量 | ¥0.50/GB | 0.5 GB | ¥0.25 |
| **合计** | - | - | **¥0.33/月** |

**年费用估算**：
- 第 1 年：3个月免费 + 9个月付费 = ¥0 + ¥2.97 ≈ **¥3**
- 第 2 年起：12个月 × ¥0.33 ≈ **¥4/年**

### 2.2 Supabase 费用

| 项目 | 免费额度 | 你的用量 | 费用 |
|------|----------|----------|------|
| 数据库存储 | 500 MB | ~150 MB（10万卡密+日志） | ¥0 |
| 数据库带宽 | 5 GB/月 | ~500 MB/月 | ¥0 |
| 并发连接 | 60 个 | Serverless 复用 | ¥0 |
| **月费用** | - | - | **¥0** |

### 2.3 总成本对比

| 方案 | 月成本 | 年成本 | 5年成本 |
|------|--------|--------|---------|
| **FC + Supabase** | ¥0.33 | ¥4 | ¥16 |
| 原 Coze 托管 | ¥460 | ¥5520 | ¥27600 |
| **节省** | ¥459.67 | ¥5516 | ¥27584 |

---

## 三、第一阶段：账号准备与数据导出

### 3.1 注册阿里云账号

#### Step 1: 注册账号

```
1. 访问 https://www.aliyun.com
2. 点击「免费注册」
3. 使用手机号注册
4. 完成手机验证
```

#### Step 2: 实名认证（必须）

```
1. 登录阿里云控制台
2. 点击右上角头像 → 实名认证
3. 选择「个人实名认证」
4. 上传身份证正反面照片
5. 等待审核（通常即时完成）
```

#### Step 3: 开通函数计算 FC

```
1. 控制台搜索「函数计算 FC」
2. 点击「立即开通」
3. 确认开通（免费开通，按量付费）
4. 选择地域：建议选择「华东1（杭州）」或「华东2（上海）」
```

#### Step 4: 获取 AccessKey（部署时需要）

```
1. 控制台右上角 → 点击头像 → AccessKey 管理
2. 选择「继续使用 AccessKey」
3. 创建 AccessKey
4. 记录 AccessKey ID 和 Secret（保密！）
```

### 3.2 注册 Supabase 账号

#### Step 1: 注册账号

```
1. 访问 https://supabase.com
2. 点击「Start your project」
3. 选择「Sign in with GitHub」（推荐）或邮箱注册
```

#### Step 2: 创建项目

```
1. 点击「New Project」
2. 填写项目信息：
   - Name: card-key-system
   - Database Password: 设置一个强密码（记住！）
   - Region: Singapore（离中国最近）
3. 点击「Create new project」
4. 等待约 2 分钟创建完成
```

#### Step 3: 获取数据库连接信息

```
1. 进入项目 Dashboard
2. 点击左侧「Settings」→「Database」
3. 找到「Connection string」→ 选择「URI」格式
4. 复制连接字符串，格式如下：
   postgresql://postgres.[PROJECT-REF]:[PASSWORD]@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres
   
注意：将 [PASSWORD] 替换为你设置的数据库密码
```

### 3.3 导出扣子数据库数据

#### 方式一：使用备份脚本

```bash
# 在扣子开发环境中执行
cd /workspace/projects
python scripts/backup_data.py

# 备份文件位置
ls -la backups/
# 输出：backup_YYYYMMDD_HHMMSS.json
```

#### 方式二：从管理后台导出

```
1. 登录管理后台：https://你的域名/admin
2. 卡密管理 → 导出 → 选择 CSV 格式
3. 卡种管理 → 导出 → 选择 CSV 格式
4. 保存导出的 CSV 文件
```

#### 方式三：直接复制数据

如果你当前在扣子开发环境中，可以直接查看数据：

```bash
# 查看现有数据
cat /workspace/projects/data_export_for_production.json
```

---

## 四、第二阶段：Supabase 数据库配置

### 4.1 创建数据表

#### Step 1: 打开 SQL Editor

```
1. 进入 Supabase 项目 Dashboard
2. 点击左侧「SQL Editor」
3. 点击「New query」
```

#### Step 2: 执行建表 SQL

复制以下 SQL 语句，在 SQL Editor 中执行：

```sql
-- ============================================
-- 1. 卡种表
-- ============================================
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

-- 卡种表索引
CREATE INDEX ix_card_types_name ON card_types(name);
CREATE INDEX ix_card_types_status ON card_types(status);

-- 添加注释
COMMENT ON TABLE card_types IS '卡种表 - 卡密分组管理';
COMMENT ON COLUMN card_types.name IS '卡种名称';
COMMENT ON COLUMN card_types.preview_image IS '预览截图URL';
COMMENT ON COLUMN card_types.preview_enabled IS '是否启用预览';
COMMENT ON COLUMN card_types.status IS '状态: 1=有效, 0=无效';
COMMENT ON COLUMN card_types.sort_order IS '排序值';

-- ============================================
-- 2. 卡密表
-- ============================================
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
    last_used_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE
);

-- 卡密表索引
CREATE INDEX ix_card_keys_key_value ON card_keys_table(key_value);
CREATE INDEX ix_card_keys_status ON card_keys_table(status);
CREATE INDEX ix_card_keys_card_type_id ON card_keys_table(card_type_id);
CREATE INDEX ix_card_keys_sale_status ON card_keys_table(sale_status);

-- 添加注释
COMMENT ON TABLE card_keys_table IS '卡密表';
COMMENT ON COLUMN card_keys_table.key_value IS '卡密值';
COMMENT ON COLUMN card_keys_table.status IS '状态: 1=有效, 0=无效';
COMMENT ON COLUMN card_keys_table.feishu_url IS '飞书链接';
COMMENT ON COLUMN card_keys_table.feishu_password IS '飞书访问密码';
COMMENT ON COLUMN card_keys_table.expire_at IS '过期时间(固定日期)';
COMMENT ON COLUMN card_keys_table.expire_after_days IS '激活后有效天数';
COMMENT ON COLUMN card_keys_table.activated_at IS '首次激活时间';
COMMENT ON COLUMN card_keys_table.max_devices IS '最大设备数';
COMMENT ON COLUMN card_keys_table.devices IS '已绑定设备ID列表(JSON)';
COMMENT ON COLUMN card_keys_table.sale_status IS '销售状态: unsold/sold/refunded/disputed';

-- ============================================
-- 3. 访问日志表
-- ============================================
CREATE TABLE access_logs (
    id SERIAL PRIMARY KEY,
    card_key_id INTEGER REFERENCES card_keys_table(id),
    key_value VARCHAR(50) NOT NULL,
    success BOOLEAN DEFAULT FALSE,
    error_msg VARCHAR(200),
    access_time TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    session_id VARCHAR(64)
);

-- 访问日志表索引
CREATE INDEX ix_access_logs_key_value ON access_logs(key_value);
CREATE INDEX ix_access_logs_access_time ON access_logs(access_time);
CREATE INDEX ix_access_logs_card_key_id ON access_logs(card_key_id);

-- 添加注释
COMMENT ON TABLE access_logs IS '访问日志表';

-- ============================================
-- 4. 链接健康表（可选）
-- ============================================
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

-- 链接健康表索引
CREATE INDEX ix_link_health_feishu_url ON link_health_table(feishu_url);
CREATE INDEX ix_link_health_status ON link_health_table(status);

-- ============================================
-- 5. 预览图片表（可选）
-- ============================================
CREATE TABLE preview_images (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    url TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 预览图片表索引
CREATE INDEX ix_preview_images_name ON preview_images(name);

-- ============================================
-- 6. 健康检查表（系统需要）
-- ============================================
CREATE TABLE health_check (
    id INTEGER PRIMARY KEY,
    updated_at TIMESTAMP WITH TIME ZONE
);

-- 插入健康检查初始数据
INSERT INTO health_check (id, updated_at) VALUES (1, NOW());
```

#### Step 3: 验证表创建成功

```sql
-- 查看所有表
SELECT table_name FROM information_schema.tables 
WHERE table_schema = 'public' 
ORDER BY table_name;

-- 应该看到以下表：
-- access_logs
-- card_keys_table
-- card_types
-- health_check
-- link_health_table
-- preview_images
```

### 4.2 导入数据

#### 方式一：使用 SQL INSERT（适合小数据量）

如果数据量较小（< 1000 条），可以直接在 SQL Editor 中执行 INSERT：

```sql
-- 导入卡种数据
INSERT INTO card_types (id, name, preview_image, preview_enabled, status, sort_order, created_at)
VALUES 
(1, 'VIP资料库', NULL, FALSE, 1, 0, NOW()),
(2, '普通资料', NULL, FALSE, 1, 1, NOW());

-- 重置序列
SELECT setval('card_types_id_seq', (SELECT MAX(id) FROM card_types));

-- 导入卡密数据（示例，需要替换为实际数据）
INSERT INTO card_keys_table (key_value, status, card_type_id, feishu_url, feishu_password, link_name, sale_status, created_at)
VALUES 
('CSS-01B2-4322-AB9F', 1, 1, 'https://xxx.feishu.cn/xxx', 'password1', 'VIP资料', 'unsold', NOW()),
('CSS-0B2E-C168-9E6B', 1, 1, 'https://xxx.feishu.cn/xxx', 'password2', 'VIP资料', 'unsold', NOW());
```

#### 方式二：使用 CSV 导入（推荐，适合大数据量）

```
1. 准备 CSV 文件
   - 从扣子管理后台导出 CSV
   - 或从 backup JSON 转换为 CSV

2. 导入步骤：
   a. Supabase Dashboard → Table Editor
   b. 选择目标表（如 card_keys_table）
   c. 点击右上角「Import data from CSV」
   d. 上传 CSV 文件
   e. 映射字段（确保列名匹配）
   f. 点击「Import」完成导入

3. 注意事项：
   - 确保 CSV 列名与表字段名一致
   - 日期格式使用 ISO 8601（YYYY-MM-DD HH:MM:SS）
   - 空值留空即可
```

#### 方式三：使用 Python 脚本导入

创建导入脚本：

```python
# scripts/import_to_supabase.py
import json
import psycopg2
from datetime import datetime

# Supabase 连接信息
DATABASE_URL = "postgresql://postgres.[PROJECT-REF]:[PASSWORD]@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres"

def import_data():
    # 读取备份数据
    with open('backups/backup_xxx.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # 连接数据库
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    # 导入卡种
    if 'card_types' in data['tables']:
        for item in data['tables']['card_types']['data']:
            cur.execute("""
                INSERT INTO card_types (id, name, preview_image, preview_enabled, status, sort_order, created_at)
                VALUES (%(id)s, %(name)s, %(preview_image)s, %(preview_enabled)s, %(status)s, %(sort_order)s, %(created_at)s)
                ON CONFLICT (id) DO NOTHING
            """, item)
    
    # 导入卡密
    if 'card_keys_table' in data['tables']:
        for item in data['tables']['card_keys_table']['data']:
            cur.execute("""
                INSERT INTO card_keys_table (key_value, status, card_type_id, feishu_url, feishu_password, link_name, sale_status, created_at)
                VALUES (%(key_value)s, %(status)s, %(card_type_id)s, %(feishu_url)s, %(feishu_password)s, %(link_name)s, %(sale_status)s, %(created_at)s)
                ON CONFLICT (key_value) DO NOTHING
            """, item)
    
    conn.commit()
    cur.close()
    conn.close()
    print("数据导入完成")

if __name__ == '__main__':
    import_data()
```

### 4.3 验证数据导入

```sql
-- 检查各表记录数
SELECT 'card_types' as table_name, COUNT(*) as count FROM card_types
UNION ALL
SELECT 'card_keys_table', COUNT(*) FROM card_keys_table
UNION ALL
SELECT 'access_logs', COUNT(*) FROM access_logs;

-- 检查卡密数据
SELECT key_value, status, feishu_url, sale_status 
FROM card_keys_table 
LIMIT 10;
```

---

## 五、第三阶段：代码适配

### 5.1 需要创建/修改的文件

```
/workspace/projects/
├── s.yaml                    # 新建：FC 部署配置（推荐使用 s 工具）
├── code/                     # 新建：FC 代码目录
│   ├── main.py              # 复制并修改：主应用
│   ├── fc_handler.py        # 新建：FC 入口适配
│   └── requirements.txt     # 复制：依赖列表
└── .env.production          # 新建：生产环境变量
```

### 5.2 创建 FC 入口文件

创建 `code/fc_handler.py`：

```python
"""
阿里云函数计算 FC 入口文件
适配 FastAPI 应用到 FC HTTP 触发器
"""
import json
import logging
from typing import Dict, Any

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 导入主应用
from main import app

# 使用 Starlette TestClient 处理请求
from starlette.testclient import TestClient

# 创建测试客户端
client = TestClient(app)


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    FC HTTP 触发器入口函数
    
    Args:
        event: HTTP 请求事件，包含：
            - method: HTTP 方法
            - path: 请求路径
            - headers: 请求头
            - queries: 查询参数
            - body: 请求体
        context: FC 上下文信息
    
    Returns:
        HTTP 响应字典
    """
    try:
        # 解析请求信息
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
        
        # 转发请求到 FastAPI
        logger.info(f"Request: {method} {path}")
        
        response = client.request(
            method=method,
            url=path,
            headers=dict(headers),
            params=params,
            content=content
        )
        
        # 构造 FC 响应
        # 过滤某些可能导致问题的响应头
        response_headers = {}
        for key, value in response.headers.items():
            # 跳过某些 hop-by-hop 头
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

### 5.3 修改主应用入口

修改 `code/main.py`（复制原 `src/main.py` 并调整）：

```python
"""
卡密验证系统主应用
适配阿里云 FC 部署
"""
import os
import logging
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 从环境变量读取数据库连接
DATABASE_URL = os.getenv('DATABASE_URL')

# 创建 FastAPI 应用
app = FastAPI(
    title="卡密验证系统",
    description="用户输入卡密后访问飞书多维表格内容",
    version="2.0.0"
)

# 挂载静态文件
static_path = os.path.join(os.path.dirname(__file__), 'static')
if os.path.exists(static_path):
    app.mount("/static", StaticFiles(directory=static_path), name="static")

# ... 复制原有的路由和业务逻辑 ...
# 注意：数据库连接使用 DATABASE_URL 环境变量

@app.get("/")
async def index():
    """用户验证页面"""
    index_path = os.path.join(os.path.dirname(__file__), 'static', 'index.html')
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse("<h1>卡密验证系统</h1>")

@app.get("/health")
async def health():
    """健康检查"""
    return {"status": "ok"}

# ... 其他路由 ...
```

### 5.4 创建 requirements.txt

```
fastapi>=0.104.0
uvicorn>=0.24.0
psycopg2-binary>=2.9.0
httpx>=0.25.0
python-dotenv>=1.0.0
pydantic>=2.0.0
python-multipart>=0.0.6
starlette>=0.27.0
```

### 5.5 创建 FC 配置文件

创建 `s.yaml`（使用阿里云 Serverless Devs 工具）：

```yaml
edition: 1.0.0
name: card-key-system
access: default

vars:
  region: cn-hangzhou  # 选择离你用户最近的地域

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
          DATABASE_URL: ${env(DATABASE_URL)}
          ADMIN_USERNAME: ${env(ADMIN_USERNAME)}
          ADMIN_PASSWORD: ${env(ADMIN_PASSWORD)}
      
      function:
        name: card-key-function
        description: 卡密验证函数
        runtime: python3.9
        codeUri: ./code
        handler: fc_handler.handler
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

### 5.6 创建环境变量文件

创建 `.env.production`：

```bash
# 数据库连接（从 Supabase 获取）
DATABASE_URL=postgresql://postgres.[PROJECT-REF]:[PASSWORD]@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres

# 管理员账号
ADMIN_USERNAME=your_admin_username
ADMIN_PASSWORD=your_admin_password

# 其他配置
ENVIRONMENT=production
```

---

## 六、第四阶段：部署上线

### 6.1 安装部署工具

```bash
# 安装 Node.js（如果还没有）
# 然后安装 Serverless Devs 工具
npm install -g @serverless-devs/s

# 验证安装
s --version
```

### 6.2 配置阿里云密钥

```bash
# 配置阿里云账号
s config add

# 按提示输入：
# - AccountID: 你的阿里云账号 ID
# - AccessKeyID: 你的 AccessKey ID
# - AccessKeySecret: 你的 AccessKey Secret
```

### 6.3 本地测试

```bash
# 进入项目目录
cd /workspace/projects

# 本地启动测试
s local start

# 测试访问
curl http://localhost:9000/health
curl http://localhost:9000/
```

### 6.4 部署到 FC

```bash
# 部署
s deploy

# 部署成功后会输出访问地址
# 例如：https://xxxxxx.cn-hangzhou.fc.aliyuncs.com
```

### 6.5 验证部署

```bash
# 测试健康检查
curl https://your-fc-url/health

# 测试用户页面
curl https://your-fc-url/

# 测试管理后台
curl https://your-fc-url/admin
```

---

## 七、测试清单

### 7.1 功能测试

| 测试项 | 测试方法 | 预期结果 |
|--------|----------|----------|
| 用户页面访问 | 访问 `/` | 显示验证页面 |
| 卡密验证 | 输入有效卡密 | 跳转到飞书内容 |
| 无效卡密 | 输入无效卡密 | 显示错误提示 |
| 管理后台登录 | 访问 `/admin` | 显示登录页面 |
| 卡密管理 | 后台操作 | 增删改查正常 |
| 数据统计 | 查看统计页面 | 数据正确 |

### 7.2 性能测试

| 测试项 | 预期值 | 实际值 |
|--------|--------|--------|
| 页面加载时间 | < 2秒 | |
| 卡密验证响应 | < 1秒 | |
| 管理后台加载 | < 3秒 | |

### 7.3 兼容性测试

| 测试项 | 测试结果 |
|--------|----------|
| Chrome 浏览器 | |
| Firefox 浏览器 | |
| Safari 浏览器 | |
| 手机浏览器 | |

---

## 八、切换上线

### 8.1 切换前检查

```
□ 新系统所有功能测试通过
□ 数据已完整迁移
□ 性能满足要求
□ 准备好回滚方案
```

### 8.2 切换步骤

```
1. 更新分享链接
   └── 原链接 → 新的 FC 域名

2. 通知用户（如需要）

3. 监控运行状态
   └── 观察日志，确保无异常

4. 保留原系统作为备份
   └── 确认新系统稳定运行后再关闭
```

### 8.3 回滚方案

如果新系统出现问题：

```
1. 立即切换回原链接
2. 检查 FC 日志定位问题
3. 修复后重新部署
```

---

## 九、后续维护

### 9.1 日常监控

| 任务 | 频率 | 方法 |
|------|------|------|
| 检查服务状态 | 每天 | 访问验证页面 |
| 查看 FC 日志 | 按需 | 阿里云控制台 |
| 检查数据库存储 | 每月 | Supabase Dashboard |
| 数据备份 | 每月 | 导出 CSV |

### 9.2 费用监控

```
阿里云控制台 → 费用中心 → 查看消费明细

关注项目：
├── 函数调用次数
├── 执行时长
└── 公网流量
```

---

## 十、常见问题

### Q1: 部署时报错 "AccessKey not found"

**解决方案**：重新配置阿里云密钥
```bash
s config add
```

### Q2: 数据库连接失败

**解决方案**：
1. 检查 DATABASE_URL 格式是否正确
2. 确认 Supabase 项目状态正常
3. 检查网络连通性

### Q3: 冷启动延迟较高

**解决方案**：
- 接受 1-3 秒的冷启动延迟（你的访问量低，影响很小）
- 或购买预留实例消除冷启动（约 ¥30-50/月）

### Q4: 飞书嵌入显示异常

**解决方案**：
- 检查飞书链接是否正确
- 确认嵌入参数是否正确

---

## 十一、联系与支持

### 阿里云支持

- 文档中心：https://help.aliyun.com/product/50980.html
- 工单系统：阿里云控制台 → 工单

### Supabase 支持

- 文档：https://supabase.com/docs
- Discord 社区：https://discord.supabase.com

---

*文档版本：1.0*
*创建时间：2026-03-28*
