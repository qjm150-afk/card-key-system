# ============================================
# 阿里云 FC 部署指南
# ============================================

## 一、已完成的服务开通

- ✅ Supabase 项目创建和数据迁移
- ✅ 阿里云函数计算 FC 3.0 开通
- ✅ 容器镜像服务个人版开通
- ✅ 镜像仓库创建

## 二、关键配置信息

### Supabase
| 项目 | 值 |
|------|-----|
| Project URL | https://ktivyspgzpxrawjtmkck.supabase.co |
| Anon Key | eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9... |

### 阿里云容器镜像
| 项目 | 值 |
|------|-----|
| 公网地址 | crpi-58hj1qq38r30k6ax.cn-hangzhou.personal.cr.aliyuncs.com |
| 内网地址 | crpi-58hj1qq38r30k6ax-vpc.cn-hangzhou.personal.cr.aliyuncs.com |
| 命名空间 | card-key |
| 仓库名 | card-key-api |
| 用户名 | aliyun3949702043 |

### 管理员
| 项目 | 值 |
|------|-----|
| 默认密码 | QJM150 |

---

## 三、部署步骤

### 方式一：控制台手动部署（推荐新手）

#### 步骤 1：构建并推送镜像

在沙箱环境执行：

```bash
# 1. 构建镜像
docker build -t crpi-58hj1qq38r30k6ax.cn-hangzhou.personal.cr.aliyuncs.com/card-key/card-key-api:latest -f Dockerfile .

# 2. 登录镜像仓库（输入你的 Registry 密码）
docker login --username=aliyun3949702043 crpi-58hj1qq38r30k6ax.cn-hangzhou.personal.cr.aliyuncs.com

# 3. 推送镜像
docker push crpi-58hj1qq38r30k6ax.cn-hangzhou.personal.cr.aliyuncs.com/card-key/card-key-api:latest
```

#### 步骤 2：创建 FC 服务

1. 访问 FC 控制台：https://fcnext.console.aliyun.com/
2. 选择区域：**华东1（杭州）**
3. 点击「创建服务」
   - 服务名称：`card-key-service`
   - 描述：卡密验证系统

#### 步骤 3：创建函数

1. 在服务下点击「创建函数」
2. 选择「使用容器镜像」
3. 配置：
   - 函数名称：`card-key-api`
   - 镜像地址：`crpi-58hj1qq38r30k6ax-vpc.cn-hangzhou.personal.cr.aliyuncs.com/card-key/card-key-api:latest`（注意用内网地址）
   - 监听端口：`5000`
   - 内存规格：`512 MB`
   - 超时时间：`60 秒`
   - 实例并发度：`1`

#### 步骤 4：配置环境变量

在函数配置中添加环境变量：

```
COZE_SUPABASE_URL=https://ktivyspgzpxrawjtmkck.supabase.co
COZE_SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imt0aXZ5c3BnenB4cmF3anRta2NrIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQ3NzkwNzIsImV4cCI6MjA5MDM1NTA3Mn0.soWTMdRYmCvJTP7QbyFTniLLaY3P0XQu6bz37ItdZbA
ADMIN_PASSWORD=QJM150
```

#### 步骤 5：配置触发器

1. 添加 HTTP 触发器
2. 配置：
   - 触发器名称：`http-trigger`
   - 路径：`/*`
   - 方法：`GET, POST, PUT, DELETE`
   - 认证方式：`匿名访问`

#### 步骤 6：测试访问

部署完成后，FC 会提供一个访问地址，格式类似：
```
https://card-key-api-xxx.cn-hangzhou.fc.aliyuncs.com
```

---

## 四、费用预估

| 项目 | 预估月费用 |
|------|-----------|
| FC 调用 | ~0.1 元 |
| FC 流量 | ~0.1 元 |
| Supabase | 0 元（免费版） |
| 容器镜像 | 0 元（个人版） |
| **总计** | **~0.2 元** |

对比扣子托管：~470 元/月 → **节省 99.96%**

---

## 五、注意事项

1. **并行运行**：扣子生产环境暂时保持不变，等 FC 环境稳定后再切换
2. **数据同步**：当前 Supabase 已有 251 条卡密，与扣子生产环境数据一致
3. **密码安全**：建议部署后修改管理员密码
