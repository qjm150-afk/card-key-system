# 阿里云 FC + Supabase 完整迁移方案

## 一、方案概览

### 1.1 架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                        最终架构                                      │
│                                                                     │
│   国内用户 ──────────▶ 阿里云 FC ──────────▶ Supabase PostgreSQL    │
│                          │                      │                   │
│                    (国内节点)               (新加坡节点)             │
│                    访问延迟 <50ms           数据库延迟 100-300ms    │
│                          │                                          │
│                          ▼                                          │
│                   飞书多维表格嵌入                                   │
│                                                                     │
│   总延迟：150-350ms（与当前扣子托管相当）                            │
│   月成本：¥0                                                        │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 数据流详解

```
用户访问流程：
                                                                    
1. 用户访问验证页面                                                  
   └── 浏览器 → 阿里云 FC（国内）→ 返回 HTML 页面
       延迟：< 50ms ✅ 快

2. 用户输入卡密验证
   └── 浏览器 → 阿里云 FC → Supabase 查询卡密 → 返回结果
       延迟：150-350ms ✅ 可接受

3. 验证成功后嵌入飞书
   └── 浏览器 → 飞书服务器 → 加载多维表格内容
       延迟：取决于飞书服务器
```

---

## 二、各组件详解

### 2.1 阿里云函数计算 FC

#### 什么是函数计算？

```
传统服务器：你需要租一台服务器，24小时运行，不管有没有人访问
函数计算：有人访问时才启动，按实际使用付费，没人访问时不花钱
```

#### 免费额度详解

| 资源类型 | 免费额度 | 你的用量 | 是否够用 |
|----------|----------|----------|----------|
| 函数调用次数 | 100 万次/月 | ~6000 次/月 | ✅ 够用 166 年 |
| 函数执行时长 | 40 万 GB-秒/月 | ~1000 GB-秒/月 | ✅ 够用 400 年 |
| 公网流出流量 | 1 GB/月 | ~500 MB/月 | ✅ 够用 |
| 公网流入流量 | 免费 | ~100 MB/月 | ✅ 免费 |

#### 计算公式

```
假设每次访问：
- 函数执行时间：500ms（0.5秒）
- 内存使用：512MB（0.5GB）
- 每次调用产生：0.5秒 × 0.5GB = 0.25 GB-秒

每天 100-300 次访问：
- 执行时长：25-75 GB-秒/天
- 月执行时长：750-2250 GB-秒/月
- 免费额度：40万 GB-秒/月
- 占用比例：0.2%-0.6%

结论：完全在免费额度内 ✅
```

#### 冷启动问题

| 场景 | 延迟 | 说明 |
|------|------|------|
| 热启动（刚访问过） | < 100ms | 正常情况 |
| 冷启动（长时间未访问） | 1-3 秒 | Python 运行时初始化 |

**你的情况**：
- 日访问量 100-300 次，平均每小时 4-12 次
- 大部分访问都是热启动
- 即使偶尔冷启动，1-3 秒也可接受

#### 消除冷启动（可选，需付费）

| 方案 | 月成本 | 效果 |
|------|--------|------|
| 预留实例 | ¥30-50/月 | 完全消除冷启动 |

**建议**：不需要，冷启动影响很小

---

### 2.2 Supabase PostgreSQL

#### 什么是 Supabase？

```
Supabase = 开源的 Firebase 替代品
- PostgreSQL 数据库（关系型数据库）
- 提供免费托管
- 自动备份
- Dashboard 可视化管理
```

#### 免费额度详解

| 资源类型 | 免费额度 | 你的用量 | 是否够用 |
|----------|----------|----------|----------|
| 数据库存储 | 500 MB | ~150 MB（10万卡密+日志） | ✅ 够用 |
| 数据库带宽 | 5 GB/月 | ~500 MB/月 | ✅ 够用 |
| 并发连接 | 60 个 | Serverless 复用连接 | ✅ 够用 |
| API 请求 | 无限制 | ~6000 次/月 | ✅ 无限制 |

#### 存储容量计算

```
10 万条卡密存储：
├── 卡密表（10万条 × 800字节）     = 80 MB
├── 卡种表（50条 × 500字节）       = 0.025 MB
├── 访问日志（1年 × 5万条 × 150字节）= 7.5 MB
├── 索引                           ≈ 20 MB
├── 系统开销                       ≈ 10 MB
└── 总计                           ≈ 117 MB

剩余空间：500 - 117 = 383 MB ✅ 充裕
```

#### 区域选择

| 区域 | 延迟（从国内） | 推荐 |
|------|----------------|------|
| Singapore（新加坡） | 100-200ms | ✅ **推荐** |
| Tokyo（东京） | 80-150ms | 可选 |
| Sydney（悉尼） | 150-250ms | 不推荐 |
| US West（美国西部） | 200-300ms | 不推荐 |

**建议**：选择 Singapore 区域，离中国最近

---

## 三、完整费用分析

### 3.1 零成本方案

| 组件 | 费用 | 说明 |
|------|------|------|
| 阿里云 FC | **¥0** | 免费额度内 |
| Supabase | **¥0** | 免费额度内 |
| 域名 | **¥0** | 使用免费域名（见下文） |
| **月成本** | **¥0** | |
| **年成本** | **¥0** | |

### 3.2 与原方案对比

| 方案 | 月成本 | 年成本 | 5年成本 |
|------|--------|--------|---------|
| 原 Coze 托管 | ¥460 | ¥5520 | **¥27600** |
| **FC + Supabase** | **¥0** | **¥0** | **¥0** |
| **节省** | **¥460** | **¥5520** | **¥27600** |

---

## 四、域名问题分析

### 4.1 免费域名方案

#### 方案 A：使用 FC 默认域名

```
格式：https://[函数名].[服务名].[区域].fc.aliyuncs.com

示例：https://card-key-function.card-key-service.cn-hangzhou.fc.aliyuncs.com

特点：
├── 完全免费 ✅
├── HTTPS 自动配置 ✅
├── 域名较长 ⚠️
└── 不需要备案 ✅（fc.aliyuncs.com 已备案）
```

**适用场景**：
- 内部使用
- 不介意域名较长
- 追求零成本

#### 方案 B：使用免费子域名服务

```
免费子域名服务：
├── DuckDNS（duckdns.org）- 免费
├── No-IP（no-ip.com）- 免费
├── EU.org - 免费（但审核较慢）
└── GitHub Pages 自定义域名 - 免费

示例：your-app.duckdns.org
```

**适用场景**：
- 需要较短的域名
- 不想花钱买域名

### 4.2 付费域名方案

#### 方案 C：购买自定义域名

| 域名类型 | 年价格 | 说明 |
|----------|--------|------|
| .com | ¥55-70 | 国际通用 |
| .cn | ¥29-39 | 需要实名认证 |
| .xyz | ¥8-15 | 最便宜 |
| .top | ¥9-15 | 较便宜 |

#### 域名备案问题

| 情况 | 是否需要备案 | 说明 |
|------|--------------|------|
| 使用 FC 默认域名 | ❌ 不需要 | fc.aliyuncs.com 已备案 |
| 使用自定义域名 + 阿里云 FC | ✅ **需要** | 国内服务器需备案 |
| 使用自定义域名 + 海外服务 | ❌ 不需要 | 但国内访问可能变慢 |

**备案流程**：
```
1. 购买域名
2. 实名认证（1-3天）
3. 提交备案申请（5-20天）
4. 备案成功后才能绑定
```

### 4.3 域名方案对比

| 方案 | 成本 | 域名示例 | 备案 | 推荐度 |
|------|------|----------|------|--------|
| **A. FC 默认域名** | **¥0** | xxx.fc.aliyuncs.com | 不需要 | ⭐⭐⭐⭐⭐ |
| B. 免费子域名 | ¥0 | xxx.duckdns.org | 不需要 | ⭐⭐⭐ |
| C. 付费域名 + 备案 | ¥30-70/年 | your-domain.com | 需要 | ⭐⭐⭐ |

### 4.4 我的建议

**阶段一：使用 FC 默认域名（免费）**

```
理由：
├── 完全免费 ✅
├── 立即可用，无需等待备案 ✅
├── 功能完整，体验无差异 ✅
└── 域名虽长，但可以接受
```

**阶段二（可选）：购买自定义域名**

```
如果业务发展需要：
├── 购买域名（¥30-70/年）
├── 完成备案（1-3周）
└── 绑定到 FC
```

---

## 五、迁移步骤详解

### 5.1 第一阶段：准备工作（1-2 小时）

#### Step 1: 注册阿里云账号

```
1. 访问 https://www.aliyun.com
2. 使用手机号注册
3. 完成实名认证（必须）
   ├── 个人认证：上传身份证，即时完成
   └── 企业认证：需要营业执照，1-3天

4. 开通函数计算 FC 服务
   └── 控制台搜索"函数计算" → 立即开通
```

#### Step 2: 注册 Supabase 账号

```
1. 访问 https://supabase.com
2. 使用 GitHub 账号登录（推荐）或邮箱注册
3. 创建新项目
   ├── 项目名称：card-key-system
   ├── 数据库密码：自己设置（记住！）
   ├── 区域：Singapore（推荐）
   └── 等待约 2 分钟创建完成

4. 获取数据库连接信息
   Settings → Database → Connection string → URI
   格式：postgresql://postgres:[PASSWORD]@db.[REF].supabase.co:5432/postgres
```

#### Step 3: 创建数据表

**方式一：使用 SQL Editor（推荐）**

```sql
-- 在 Supabase Dashboard → SQL Editor 中执行

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
    expire_after_days INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE
);

-- 3. 访问日志表
CREATE TABLE access_logs (
    id SERIAL PRIMARY KEY,
    card_key_id INTEGER REFERENCES card_keys_table(id),
    key_value VARCHAR(50) NOT NULL,
    success BOOLEAN DEFAULT FALSE,
    error_msg VARCHAR(200),
    access_time TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    session_id VARCHAR(64)
);

-- 4. 创建索引
CREATE INDEX ix_card_keys_key_value ON card_keys_table(key_value);
CREATE INDEX ix_card_keys_status ON card_keys_table(status);
CREATE INDEX ix_card_keys_card_type_id ON card_keys_table(card_type_id);
CREATE INDEX ix_access_logs_key_value ON access_logs(key_value);
CREATE INDEX ix_access_logs_access_time ON access_logs(access_time);

-- 5. 链接健康表（可选）
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

-- 6. 预览图片表（可选）
CREATE TABLE preview_images (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    url TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

**方式二：使用 Table Editor 图形化创建**

```
Table Editor → Create a new table
逐个创建表，设置字段类型
```

#### Step 4: 导出现有数据

```bash
# 从扣子环境导出数据
# 方式一：使用现有脚本
python scripts/backup_data.py

# 方式二：从管理后台导出
# 访问管理后台 → 卡密管理 → 导出 → CSV
# 访问管理后台 → 卡种管理 → 导出 → CSV
```

#### Step 5: 导入数据到 Supabase

**方式一：CSV 导入**

```
1. Supabase Dashboard → Table Editor
2. 选择目标表
3. 点击 Import → 选择 CSV 文件
4. 映射字段
5. 确认导入
```

**方式二：SQL INSERT**

```sql
-- 适合数据量大的情况
-- 在 SQL Editor 中执行 INSERT 语句
```

---

### 5.2 第二阶段：代码适配（2-3 小时）

#### 需要创建/修改的文件

```
/workspace/projects/
├── template.yml          # 新建：FC 配置文件
├── src/
│   ├── fc_main.py       # 新建：FC 入口文件
│   └── main.py          # 修改：环境变量适配
└── requirements.txt     # 检查：确保依赖完整
```

#### template.yml 配置

```yaml
ROSTemplateFormatVersion: '2015-09-01'
Transform: 'Aliyun::Serverless-2018-04-03'
Resources:
  card-key-service:
    Type: 'Aliyun::Serverless::Service'
    Properties:
      Description: 卡密验证服务
      MemorySize: 512
      Timeout: 60
      Runtime: python3.9
      EnvironmentVariables:
        DATABASE_URL: ${DATABASE_URL}
        ADMIN_USERNAME: ${ADMIN_USERNAME}
        ADMIN_PASSWORD: ${ADMIN_PASSWORD}
        
    card-key-function:
      Type: 'Aliyun::Serverless::Function'
      Properties:
        Handler: src.fc_main.handler
        CodeUri: ./
        Runtime: python3.9
        Timeout: 60
        MemorySize: 512
        
      HttpTrigger:
        Type: HTTP
        Properties:
          AuthType: anonymous
          Methods:
            - GET
            - POST
            - PUT
            - DELETE
```

#### fc_main.py 入口文件

```python
"""
阿里云 FC 入口文件
"""
import json
from main import app
from starlette.testclient import TestClient

# 创建测试客户端
client = TestClient(app)

def handler(event, context):
    """
    FC 入口函数
    
    event: HTTP 请求事件
    context: FC 上下文
    """
    try:
        # 解析请求
        if isinstance(event, str):
            event = json.loads(event)
        
        # 获取请求信息
        method = event.get('method', 'GET')
        path = event.get('path', '/')
        headers = event.get('headers', {})
        query_string = event.get('queries', {})
        body = event.get('body', '')
        
        # 转发请求到 FastAPI
        response = client.request(
            method=method,
            url=path,
            headers=headers,
            params=query_string,
            content=body if body else None
        )
        
        # 返回响应
        return {
            'statusCode': response.status_code,
            'headers': dict(response.headers),
            'body': response.text
        }
        
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
```

#### 环境变量配置

```bash
# 在阿里云 FC 控制台配置
# 或者在 template.yml 中硬编码（不推荐）

DATABASE_URL=postgresql://postgres:[PASSWORD]@db.[REF].supabase.co:5432/postgres
ADMIN_USERNAME=your_admin_username
ADMIN_PASSWORD=your_admin_password
```

---

### 5.3 第三阶段：部署测试（1-2 小时）

#### 方式一：使用阿里云控制台（推荐新手）

```
1. 控制台 → 函数计算 FC
2. 创建服务 → card-key-service
3. 创建函数 → card-key-function
4. 上传代码（打包 zip）
5. 配置环境变量
6. 创建 HTTP 触发器
7. 测试访问
```

#### 方式二：使用 Funcraft 命令行（推荐熟悉后）

```bash
# 安装 Funcraft
npm install -g @alicloud/fun

# 配置账号
fun config

# 部署
fun deploy

# 查看日志
fun logs
```

#### 测试清单

```
□ 验证页面能否正常访问
□ 管理后台能否正常登录
□ 卡密验证功能是否正常
□ 飞书嵌入是否正常显示
□ 数据增删改查是否正常
□ 导入导出功能是否正常
```

---

### 5.4 第四阶段：切换上线（1 小时）

#### Step 1: 全面测试

```
用户端测试：
├── 访问验证页面
├── 输入测试卡密
├── 验证成功后查看飞书内容
└── 检查各种边界情况

管理端测试：
├── 登录管理后台
├── 查看卡密列表
├── 新增/编辑/删除卡密
├── 查看统计数据
└── 导入/导出功能
```

#### Step 2: 数据同步

```
如果迁移期间有新数据产生：
1. 导出新增数据
2. 导入到 Supabase
3. 验证数据完整性
```

#### Step 3: 切换流量

```
1. 更新分享链接
   └── 原链接 → 新的 FC 域名

2. 通知用户（如需要）

3. 监控运行状态
   └── 观察日志，确保无异常

4. 关闭原扣子服务
   └── 停止计费
```

---

## 六、风险与应对

### 6.1 技术风险

| 风险 | 可能性 | 影响 | 应对措施 |
|------|--------|------|----------|
| FC 冷启动延迟 | 高 | 低 | 接受，或购买预留实例 |
| Supabase 连接超时 | 低 | 中 | 添加重试机制，设置超时时间 |
| 数据库查询慢 | 低 | 中 | 添加索引，优化查询 |
| 免费额度超限 | 极低 | 中 | 监控用量，设置告警 |

### 6.2 业务风险

| 风险 | 可能性 | 影响 | 应对措施 |
|------|--------|------|----------|
| 迁移期间服务中断 | 中 | 高 | 选择低峰期迁移，准备好回滚方案 |
| 数据丢失 | 低 | 高 | 多次备份，验证数据完整性 |
| 用户访问异常 | 低 | 中 | 充分测试，准备好客服支持 |

### 6.3 应对方案

```
回滚方案：
1. 保留原扣子服务，直到新系统稳定运行
2. 导出 Supabase 数据，可随时迁移到其他平台
3. 代码版本管理，可随时回退
```

---

## 七、时间规划

### 7.1 总体时间

| 阶段 | 时间 | 内容 |
|------|------|------|
| 准备工作 | 1-2 小时 | 注册账号、创建数据库 |
| 数据迁移 | 1-2 小时 | 导出、导入数据 |
| 代码适配 | 2-3 小时 | 创建配置、适配入口 |
| 部署测试 | 1-2 小时 | 部署、功能测试 |
| 切换上线 | 1 小时 | 切换流量、监控 |
| **总计** | **6-10 小时** | 可分 2-3 天完成 |

### 7.2 建议时间安排

```
第 1 天：
├── 注册阿里云账号
├── 注册 Supabase 账号
├── 创建数据库表
└── 导出现有数据

第 2 天：
├── 导入数据到 Supabase
├── 创建 FC 配置文件
├── 适配入口代码
└── 本地测试

第 3 天：
├── 部署到 FC
├── 全面测试
└── 切换上线
```

---

## 八、后续维护

### 8.1 日常维护

| 任务 | 频率 | 说明 |
|------|------|------|
| 检查服务状态 | 每周 | 访问验证页面，确保正常 |
| 查看日志 | 按需 | 排查问题时查看 |
| 数据备份 | 每月 | 导出数据到本地 |
| 清理日志 | 每季度 | 删除旧访问日志 |

### 8.2 监控告警

```
阿里云 FC 监控：
├── 控制台 → 函数计算 → 监控
├── 查看调用次数、执行时长、错误率
└── 设置告警（可选）

Supabase 监控：
├── Dashboard → Logs
├── 查看数据库查询日志
└── Settings → Database → 查看存储使用
```

### 8.3 成本监控

```
定期检查：
├── FC 用量是否接近免费额度
├── Supabase 存储是否接近 500MB
└── 如果接近，考虑优化或升级
```

---

## 九、总结

### 9.1 最终方案

```
┌─────────────────────────────────────────────────────────┐
│                 推荐方案：FC + Supabase                  │
│                                                         │
│   计算平台：阿里云 FC（国内节点）                        │
│   数据库：Supabase PostgreSQL（新加坡节点）              │
│   域名：FC 默认域名（免费）                              │
│                                                         │
│   月成本：¥0                                            │
│   年成本：¥0                                            │
│   年节省：¥5520                                         │
│                                                         │
│   迁移时间：6-10 小时                                   │
│   维护成本：极低                                        │
└─────────────────────────────────────────────────────────┘
```

### 9.2 决策确认

| 问题 | 答案 |
|------|------|
| 是否零成本？ | ✅ 是 |
| 是否需要买域名？ | ❌ 不需要 |
| 是否需要备案？ | ❌ 不需要 |
| 功能是否完整？ | ✅ 100% 保留 |
| 用户门槛？ | ✅ 无门槛 |
| 维护复杂度？ | ✅ 低 |

### 9.3 下一步

确认开始迁移后，我可以：

1. ✅ 帮你创建 FC 配置文件（template.yml）
2. ✅ 帮你创建 FC 入口文件（fc_main.py）
3. ✅ 提供完整的 SQL 建表脚本
4. ✅ 提供详细的操作截图说明
5. ✅ 协助排查部署过程中的问题

---

*文档创建时间：2026-03-28*
