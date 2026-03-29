# Supabase 迁移指南

## ✅ 已完成

1. [x] 创建 Supabase 项目
2. [x] 获取 Project URL 和 Anon Key
3. [x] 在 Supabase 中创建表结构

---

## 📋 下一步：数据迁移

### 方式一：如果你有扣子数据库的访问权限

#### 1. 获取扣子数据库连接信息

在扣子平台的**环境变量**设置中，查找以下信息：

```
PGHOST=cp-magic-vapor-xxxxx.pg5.aidap-global.cn-beijing.volces.com
PGPORT=5432
PGDATABASE=postgres
PGUSER=postgres
PGPASSWORD=xxxxxx
```

#### 2. 设置环境变量

```bash
# 源数据库（扣子）
export SOURCE_PGHOST=你的扣子数据库地址
export SOURCE_PGPORT=5432
export SOURCE_PGDATABASE=postgres
export SOURCE_PGUSER=postgres
export SOURCE_PGPASSWORD=你的密码

# 目标数据库（Supabase）
export SUPABASE_URL=https://ktivyspgzpxrawjtmkckr.supabase.co
export SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imt0aXZ5c3BnenB4cmF3anRta2NrIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQ3NzkwNzIsImV4cCI6MjA5MDM1NTA3Mn0.soWTMdRYmCvJTP7QbyFTniLLaY3P0XQu6bz37ItdZbA

# 兼容旧代码
export COZE_SUPABASE_URL=https://ktivyspgzpxrawjtmkckr.supabase.co
export COZE_SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imt0aXZ5c3BnenB4cmF3anRta2NrIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQ3NzkwNzIsImV4cCI6MjA5MDM1NTA3Mn0.soWTMdRYmCvJTP7QbyFTniLLaY3P0XQu6bz37ItdZbA
```

#### 3. 运行迁移脚本

```bash
cd /workspace/projects
python scripts/migrate_to_supabase.py
```

---

### 方式二：如果没有扣子数据库访问权限

如果你无法获取扣子数据库的连接信息，可以：

1. **手动重新创建数据**：
   - 登录管理后台重新添加卡种和卡密
   - 这是更安全的方式，避免迁移旧数据

2. **联系扣子平台**：
   - 请求导出你的数据

---

## 🚀 迁移后验证

数据迁移完成后，验证以下功能：

1. 访问新的管理后台 URL
2. 登录管理后台
3. 检查卡种和卡密数据是否正确
4. 测试卡密验证功能

---

## 📞 需要帮助？

如果你不确定如何获取扣子数据库的连接信息，请告诉我：
- 你是否有扣子平台的环境变量访问权限
- 或者你更倾向于手动重新创建数据
