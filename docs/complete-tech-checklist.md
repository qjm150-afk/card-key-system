# 卡密验证系统 - 完整技术需求清单

## 一、系统核心流程

```
┌─────────────────────────────────────────────────────────────────────┐
│                        完整业务流程                                  │
│                                                                     │
│   管理员                        用户                                │
│     │                            │                                  │
│     ▼                            │                                  │
│  ┌─────────┐                     │                                  │
│  │ 后台登录 │                     │                                  │
│  └────┬────┘                     │                                  │
│       ▼                          │                                  │
│  ┌─────────┐                     │                                  │
│  │ 创建卡种 │                     │                                  │
│  └────┬────┘                     │                                  │
│       ▼                          │                                  │
│  ┌─────────┐    分发卡密    ┌────┴────┐                             │
│  │ 生成卡密 │──────────────▶│ 输入卡密 │                             │
│  └─────────┘                └────┬────┘                             │
│                                  ▼                                  │
│                             ┌─────────┐                             │
│                             │ 验证卡密 │                             │
│                             └────┬────┘                             │
│                                  ▼                                  │
│                        ┌────────────────┐                           │
│                        │ 验证通过？      │                           │
│                        └───────┬────────┘                           │
│                          是 │  │ 否                                 │
│                             ▼  ▼                                    │
│                    ┌─────────┐ ┌─────────┐                          │
│                    │ 展示内容 │ │ 错误提示 │                          │
│                    └────┬────┘ └─────────┘                          │
│                         ▼                                           │
│                  ┌──────────────┐                                   │
│                  │ 飞书内容嵌入  │                                   │
│                  │ (隐藏原应用)  │                                   │
│                  └──────────────┘                                   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 二、需要开发的功能模块

### 2.1 前端页面（3个页面）

| 页面 | 路由 | 功能描述 |
|------|------|----------|
| 用户验证页 | `/` | 用户输入卡密、验证结果展示、飞书内容嵌入 |
| 管理后台登录 | `/admin/login` | 管理员登录页面 |
| 管理后台主页 | `/admin` | 卡密管理、卡种管理、数据统计 |

### 2.2 后端 API（10+ 个接口）

#### 用户相关 API

| 接口 | 方法 | 功能 |
|------|------|------|
| `/api/verify` | POST | 验证卡密 |
| `/api/content/{key}` | GET | 获取验证通过后的内容 |
| `/api/check-device` | POST | 检查设备绑定状态 |

#### 管理后台 API

| 接口 | 方法 | 功能 |
|------|------|------|
| `/api/admin/login` | POST | 管理员登录 |
| `/api/admin/card-types` | GET/POST | 卡种列表/创建 |
| `/api/admin/card-types/{id}` | GET/PUT/DELETE | 卡种详情/更新/删除 |
| `/api/admin/cards` | GET/POST | 卡密列表/批量生成 |
| `/api/admin/cards/{id}` | GET/PUT/DELETE | 卡密详情/更新/删除 |
| `/api/admin/stats` | GET | 数据统计 |
| `/api/admin/export` | GET | 导出卡密 |

---

## 三、详细技术需求

### 3.1 用户验证页面（`/`）

#### 功能需求

```
1. 卡密输入框
   ├── 输入验证（格式校验）
   └── 提交按钮

2. 验证结果展示
   ├── 成功：显示飞书嵌入内容
   ├── 失败：显示错误提示
   └── 加载状态

3. 飞书内容嵌入
   ├── iframe 嵌入飞书多维表格
   ├── 隐藏"进入原应用"按钮（核心技术点）
   └── 自适应高度

4. 其他功能
   ├── 记住当前会话（localStorage）
   ├── 过期提示
   └── 设备数量超限提示
```

#### 技术实现要点

**① 飞书嵌入隐藏"进入原应用"按钮**

这是你最关心的核心需求，有三种方案：

| 方案 | 原理 | 可行性 | 难度 |
|------|------|--------|------|
| **方案A：iframe + CSS 覆盖** | 通过 CSS 遮罩覆盖按钮 | ❌ 不行 | - |
| **方案B：飞书开放平台 API** | 使用官方嵌入组件 | ✅ 可行 | ⭐⭐ |
| **方案C：代理转发** | 服务端代理飞书页面 | ⚠️ 有风险 | ⭐⭐⭐ |

**推荐方案B：飞书开放平台嵌入**

```html
<!-- 方案B：使用飞书官方嵌入组件 -->
<div id="feishu-container"></div>

<script src="https://lf1-cdn-tos.bytegoofy.com/obj/bitable-ui/bitable-embed.js"></script>
<script>
BitableEmbed.create({
  container: '#feishu-container',
  url: 'https://xxx.feishu.cn/base/xxx',
  // 关键配置：隐藏工具栏
  hideToolbar: true,
  // 或使用嵌入式链接
});
</script>
```

**飞书多维表格嵌入链接格式**：

```
标准链接：https://xxx.feishu.cn/base/xxx?table=xxx&view=xxx

嵌入链接（推荐）：
https://xxx.feishu.cn/base/xxx?table=xxx&view=xxx&embed=true

或者使用飞书提供的嵌入码：
在飞书多维表格 → 分享 → 嵌入 → 复制嵌入代码
```

**② 设备绑定逻辑**

```javascript
// 前端生成设备指纹
async function generateDeviceId() {
  const data = {
    userAgent: navigator.userAgent,
    screen: `${screen.width}x${screen.height}`,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    language: navigator.language,
    platform: navigator.platform
  };
  
  // 使用简单哈希生成设备ID
  const deviceId = await crypto.subtle.digest(
    'SHA-256',
    new TextEncoder().encode(JSON.stringify(data))
  ).then(hash => {
    return Array.from(new Uint8Array(hash))
      .map(b => b.toString(16).padStart(2, '0'))
      .join('').substring(0, 32);
  });
  
  return deviceId;
}
```

**③ 会话保持**

```javascript
// 验证成功后保存会话
function saveSession(keyValue, sessionToken) {
  localStorage.setItem('card_session', JSON.stringify({
    key: keyValue,
    token: sessionToken,
    timestamp: Date.now()
  }));
}

// 页面加载时检查会话
function checkSession() {
  const session = localStorage.getItem('card_session');
  if (session) {
    const { key, token, timestamp } = JSON.parse(session);
    // 检查是否过期（7天有效期）
    if (Date.now() - timestamp < 7 * 24 * 60 * 60 * 1000) {
      return { key, token };
    }
  }
  return null;
}
```

---

### 3.2 管理后台（`/admin`）

#### 功能需求

```
1. 登录页面
   ├── 用户名/密码输入
   ├── 登录验证
   └── Session 管理

2. 仪表盘
   ├── 卡密统计（总数、已激活、未激活）
   ├── 今日访问量
   └── 快捷操作入口

3. 卡种管理
   ├── 卡种列表
   ├── 新建卡种
   ├── 编辑卡种
   └── 删除卡种

4. 卡密管理
   ├── 卡密列表（分页、搜索、筛选）
   ├── 批量生成卡密
   ├── 编辑卡密信息
   ├── 删除卡密
   └── 导出卡密

5. 访问日志
   ├── 日志列表
   ├── 搜索筛选
   └── 导出日志

6. 系统设置
   ├── 管理员密码修改
   └── 其他配置
```

#### 卡密批量生成逻辑

```python
import random
import string
from datetime import datetime, timedelta

def generate_card_keys(
    count: int,
    card_type_id: int,
    feishu_url: str,
    feishu_password: str = None,
    expire_after_days: int = None,
    prefix: str = "CSS"
) -> list:
    """
    批量生成卡密
    
    Args:
        count: 生成数量
        card_type_id: 卡种ID
        feishu_url: 飞书链接
        feishu_password: 飞书访问密码
        expire_after_days: 激活后有效天数
        prefix: 卡密前缀
    """
    keys = []
    for _ in range(count):
        # 生成卡密：PREFIX-XXXX-XXXX-XXXX
        segments = [
            prefix,
            ''.join(random.choices(string.ascii_uppercase + string.digits, k=4)),
            ''.join(random.choices(string.digits, k=4)),
            ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        ]
        key_value = '-'.join(segments)
        
        keys.append({
            'key_value': key_value,
            'status': 1,
            'card_type_id': card_type_id,
            'feishu_url': feishu_url,
            'feishu_password': feishu_password,
            'expire_after_days': expire_after_days,
            'sale_status': 'unsold',
            'created_at': datetime.now()
        })
    
    return keys
```

---

### 3.3 后端 API 详解

#### 验证卡密接口（核心）

```python
# API: POST /api/verify
# 请求体
{
    "key": "CSS-01B2-4322-AB9F",
    "device_id": "abc123..."
}

# 响应
{
    "success": true,
    "data": {
        "content_url": "https://xxx.feishu.cn/base/xxx?embed=true",
        "content_password": "123456",
        "expire_at": "2025-12-31 23:59:59",
        "session_token": "sess_xxx"
    }
}
# 或
{
    "success": false,
    "error": {
        "code": "KEY_INVALID",
        "message": "卡密无效或已过期"
    }
}
```

```python
# 后端逻辑
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

class VerifyRequest(BaseModel):
    key: str
    device_id: str

class VerifyResponse(BaseModel):
    success: bool
    data: dict = None
    error: dict = None

@router.post("/api/verify", response_model=VerifyResponse)
async def verify_card_key(request: VerifyRequest):
    """验证卡密"""
    
    # 1. 查询卡密
    card = await db.query_card_key(request.key)
    
    # 2. 检查卡密是否存在
    if not card:
        return VerifyResponse(
            success=False,
            error={"code": "KEY_NOT_FOUND", "message": "卡密不存在"}
        )
    
    # 3. 检查卡密状态
    if card.status != 1:
        return VerifyResponse(
            success=False,
            error={"code": "KEY_DISABLED", "message": "卡密已被禁用"}
        )
    
    # 4. 检查过期时间
    if card.expire_at and card.expire_at < datetime.now():
        return VerifyResponse(
            success=False,
            error={"code": "KEY_EXPIRED", "message": "卡密已过期"}
        )
    
    # 5. 检查设备绑定
    devices = card.devices or []
    if request.device_id not in devices:
        if len(devices) >= card.max_devices:
            return VerifyResponse(
                success=False,
                error={"code": "DEVICE_LIMIT", "message": f"设备数量已达上限({card.max_devices}台)"}
            )
        # 绑定新设备
        devices.append(request.device_id)
        await db.update_card_key(request.key, devices=devices)
    
    # 6. 首次激活处理
    if not card.activated_at:
        await db.update_card_key(
            request.key, 
            activated_at=datetime.now(),
            sale_status='sold'
        )
    
    # 7. 更新访问时间
    await db.update_card_key(request.key, last_used_at=datetime.now())
    
    # 8. 记录访问日志
    await db.create_access_log(
        card_key_id=card.id,
        key_value=request.key,
        success=True
    )
    
    # 9. 计算实际过期时间
    expire_at = card.expire_at
    if card.expire_after_days and card.activated_at:
        expire_at = card.activated_at + timedelta(days=card.expire_after_days)
    
    # 10. 返回内容
    return VerifyResponse(
        success=True,
        data={
            "content_url": card.feishu_url + "?embed=true",
            "content_password": card.feishu_password,
            "expire_at": expire_at.isoformat() if expire_at else None,
            "session_token": generate_session_token(card.id)
        }
    )
```

#### 批量生成卡密接口

```python
# API: POST /api/admin/cards/generate
# 请求体
{
    "count": 100,
    "card_type_id": 1,
    "feishu_url": "https://xxx.feishu.cn/base/xxx",
    "feishu_password": "123456",
    "expire_after_days": 30,
    "prefix": "CSS"
}

# 响应
{
    "success": true,
    "data": {
        "count": 100,
        "keys": ["CSS-XXXX-XXXX-XXXX", ...]
    }
}
```

---

### 3.4 飞书嵌入实现（核心技术点）

#### 方案详解

**方案一：使用飞书官方嵌入功能（推荐）**

```
1. 在飞书多维表格中：
   ├── 点击右上角「分享」
   ├── 选择「嵌入」
   ├── 配置嵌入选项：
   │   ├── 允许查看
   │   ├── 隐藏工具栏（如果支持）
   │   └── 设置访问密码
   └── 复制嵌入代码或链接

2. 嵌入链接格式：
   https://xxx.feishu.cn/base/xxx?table=xxx&view=xxx&embed=true
   
3. 如果需要隐藏更多元素：
   └── 考虑使用飞书开放平台 API
```

**方案二：使用飞书开放平台 Bitable API**

```python
# 如果需要更精细的控制，可以使用飞书开放平台 API
# 需要先注册飞书开发者账号

import httpx

async def get_feishu_bitable_data(app_token: str, table_id: str):
    """通过 API 获取多维表格数据"""
    
    # 获取 access_token
    async with httpx.AsyncClient() as client:
        # 获取 tenant_access_token
        resp = await client.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={
                "app_id": "your_app_id",
                "app_secret": "your_app_secret"
            }
        )
        token = resp.json()["tenant_access_token"]
        
        # 获取表格数据
        resp = await client.get(
            f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        return resp.json()
```

**方案三：自建内容展示页面**

```html
<!-- 如果飞书嵌入无法满足需求，可以自己搭建内容展示页面 -->
<div class="content-container">
  <!-- 顶部工具栏 -->
  <div class="toolbar">
    <h2>资料名称</h2>
    <span class="expire-info">有效期至：2025-12-31</span>
  </div>
  
  <!-- 飞书 iframe -->
  <iframe 
    src="https://xxx.feishu.cn/base/xxx?embed=true"
    class="feishu-iframe"
    sandbox="allow-scripts allow-same-origin"
  ></iframe>
  
  <!-- CSS 覆盖层（尝试隐藏元素，可能受跨域限制） -->
  <style>
    /* 这个方案通常不工作，因为有跨域限制 */
    .feishu-iframe::after {
      content: '';
      position: absolute;
      top: 0;
      right: 0;
      width: 120px;
      height: 40px;
      background: white;
    }
  </style>
</div>
```

#### 飞书嵌入最佳实践

```html
<!-- 推荐的嵌入方式 -->
<div class="feishu-embed-container">
  <!-- 如果有密码保护，先显示密码输入 -->
  <div class="password-overlay" id="passwordOverlay">
    <div class="password-box">
      <p>请输入访问密码</p>
      <input type="password" id="accessPassword" />
      <button onclick="submitPassword()">确认</button>
    </div>
  </div>
  
  <!-- 飞书嵌入 iframe -->
  <iframe 
    id="feishuFrame"
    src=""
    style="width: 100%; height: calc(100vh - 60px); border: none;"
    sandbox="allow-scripts allow-same-origin allow-forms"
  ></iframe>
</div>

<script>
// 验证成功后设置 iframe src
function loadFeishuContent(url, password) {
  const iframe = document.getElementById('feishuFrame');
  
  // 如果有密码，显示密码提示
  if (password) {
    document.getElementById('passwordOverlay').style.display = 'flex';
    document.getElementById('accessPassword').value = password;
  }
  
  // 设置 iframe 源
  // 使用 embed 参数
  iframe.src = url.includes('?') 
    ? url + '&embed=true' 
    : url + '?embed=true';
}

function submitPassword() {
  // 隐藏密码输入框
  document.getElementById('passwordOverlay').style.display = 'none';
}
</script>
```

---

## 四、完整文件结构

### 4.1 后端文件结构

```
code/
├── main.py                    # FastAPI 主入口
├── fc_handler.py              # FC 适配器
├── requirements.txt           # 依赖
├── config.py                  # 配置管理
├── database.py                # 数据库连接
│
├── models/                    # 数据模型
│   ├── __init__.py
│   ├── card_type.py          # 卡种模型
│   ├── card_key.py           # 卡密模型
│   └── access_log.py         # 访问日志模型
│
├── routers/                   # API 路由
│   ├── __init__.py
│   ├── verify.py             # 用户验证接口
│   ├── admin.py              # 管理后台接口
│   └── health.py             # 健康检查
│
├── services/                  # 业务逻辑
│   ├── __init__.py
│   ├── card_service.py       # 卡密业务逻辑
│   └── device_service.py     # 设备绑定逻辑
│
└── static/                    # 前端静态文件
    ├── index.html            # 用户验证页面
    ├── admin/                # 管理后台
    │   ├── index.html
    │   ├── login.html
    │   └── assets/
    ├── css/
    │   └── style.css
    └── js/
        ├── verify.js         # 验证页面逻辑
        └── admin.js          # 管理后台逻辑
```

### 4.2 前端文件结构

```
code/static/
├── index.html                 # 用户验证页面
│
├── admin/                     # 管理后台
│   ├── index.html            # 后台主页
│   ├── login.html            # 登录页
│   └── assets/               # 静态资源
│
├── css/
│   ├── style.css             # 全局样式
│   ├── verify.css            # 验证页面样式
│   └── admin.css             # 管理后台样式
│
└── js/
    ├── verify.js             # 验证页面逻辑
    ├── admin.js              # 管理后台逻辑
    └── utils.js              # 工具函数
```

---

## 五、技术实现优先级

### 5.1 核心功能（必须实现）

| 优先级 | 功能 | 说明 |
|--------|------|------|
| P0 | 卡密验证接口 | 核心业务逻辑 |
| P0 | 飞书嵌入展示 | 用户最终目的 |
| P0 | 管理后台登录 | 管理入口 |
| P0 | 卡密生成/管理 | 核心功能 |
| P1 | 设备绑定 | 防止滥用 |
| P1 | 过期时间控制 | 业务需求 |

### 5.2 辅助功能（推荐实现）

| 优先级 | 功能 | 说明 |
|--------|------|------|
| P2 | 访问日志 | 便于排查问题 |
| P2 | 卡种管理 | 分组管理 |
| P2 | 数据统计 | 了解使用情况 |
| P2 | 批量导出 | 方便分发卡密 |

### 5.3 可选功能（后期优化）

| 优先级 | 功能 | 说明 |
|--------|------|------|
| P3 | 销售状态管理 | 如果需要记录销售情况 |
| P3 | 链接健康检查 | 监控飞书链接有效性 |
| P3 | 预览图功能 | 卡种预览 |

---

## 六、开发工作量估算

### 6.1 后端开发

| 模块 | 工作内容 | 预估时间 |
|------|----------|----------|
| 基础框架 | FastAPI 项目搭建、数据库连接 | 2-3小时 |
| 用户API | 验证接口、内容接口 | 3-4小时 |
| 管理API | 登录、卡密管理、卡种管理、统计 | 4-5小时 |
| 业务逻辑 | 设备绑定、过期处理、日志记录 | 2-3小时 |
| **小计** | | **11-15小时** |

### 6.2 前端开发

| 模块 | 工作内容 | 预估时间 |
|------|----------|----------|
| 用户验证页面 | 输入框、验证逻辑、内容展示 | 3-4小时 |
| 飞书嵌入 | iframe 嵌入、样式调整 | 2-3小时 |
| 管理后台 | 登录页、主页、卡密管理、统计 | 5-6小时 |
| **小计** | | **10-13小时** |

### 6.3 总工作量

| 阶段 | 时间 |
|------|------|
| 后端开发 | 11-15小时 |
| 前端开发 | 10-13小时 |
| 测试调试 | 3-5小时 |
| **总计** | **24-33小时** |

---

## 七、关键技术决策

### 7.1 飞书嵌入方案选择

| 方案 | 优点 | 缺点 | 推荐度 |
|------|------|------|--------|
| iframe + embed参数 | 简单易用 | 可能显示工具栏 | ⭐⭐⭐ |
| 飞书嵌入组件 | 官方支持、可配置 | 需要引入SDK | ⭐⭐⭐⭐ |
| 飞书 API | 完全控制、自定义展示 | 开发量大、需开发者账号 | ⭐⭐ |

**推荐**：先尝试 `iframe + embed参数`，如果不满意再考虑嵌入组件。

### 7.2 设备绑定方案

| 方案 | 优点 | 缺点 | 推荐度 |
|------|------|------|--------|
| 简单指纹 | 实现简单、用户体验好 | 可能被绕过 | ⭐⭐⭐ |
| 复杂指纹 | 更难绕过 | 可能误判 | ⭐⭐ |

**推荐**：简单指纹方案，你的场景不需要太严格的安全控制。

### 7.3 管理后台技术选择

| 方案 | 优点 | 缺点 | 推荐度 |
|------|------|------|--------|
| 纯 HTML + JS | 简单、无需构建 | 代码组织性差 | ⭐⭐ |
| Vue.js SPA | 组件化、易维护 | 需要构建 | ⭐⭐⭐⭐ |
| 服务端渲染 | SEO友好 | 开发效率低 | ⭐⭐ |

**推荐**：如果追求快速上线，用纯 HTML + JS；如果追求代码质量，用 Vue.js。

---

## 八、下一步行动建议

### 8.1 立即可以开始的工作

```
1. 导出现有数据
   └── 执行数据备份脚本

2. 创建 Supabase 数据库
   └── 按迁移方案执行建表 SQL

3. 飞书嵌入测试
   └── 先测试 embed 参数是否能满足需求
```

### 8.2 需要你确认的问题

```
1. 飞书嵌入需求
   ├── 你希望完全隐藏"进入原应用"按钮吗？
   ├── 如果不能完全隐藏，是否可以接受？
   └── 是否需要密码保护？

2. 设备绑定需求
   ├── 每个卡密限制多少设备？（默认5台）
   ├── 是否需要设备解绑功能？
   └── 是否需要显示已绑定设备列表？

3. 卡密生成规则
   ├── 卡密格式是什么？（默认 CSS-XXXX-XXXX-XXXX）
   ├── 是否需要批量生成？
   └── 是否需要导出功能？

4. 管理后台需求
   ├── 需要哪些统计数据？
   ├── 是否需要访问日志？
   └── 是否需要多管理员？
```

---

*文档版本：1.0*
*创建时间：2026-03-28*
