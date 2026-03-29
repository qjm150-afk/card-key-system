# 迁移检查清单

## 一、迁移前准备

### 1.1 Supabase 准备

- [ ] 创建 Supabase 账号
- [ ] 创建新项目
- [ ] 记录 Project URL
- [ ] 记录 Anon Key
- [ ] 记录数据库连接字符串
- [ ] 执行 `supabase_schema.sql` 创建表结构

### 1.2 阿里云准备

- [ ] 创建阿里云账号
- [ ] 开通函数计算服务
- [ ] 开通容器镜像服务
- [ ] 安装 Serverless DevTools (`npm install -g @serverless-devs/s`)
- [ ] 配置阿里云凭证 (`s config add`)

### 1.3 关闭扣子计费项

- [ ] 关闭 Trace 日志上报
- [ ] 备份当前项目配置
- [ ] 记录当前访问域名

---

## 二、数据迁移

### 2.1 导出数据

```bash
# 设置扣子数据库环境变量
export PGHOST=cp-magic-vapor-xxxxx.pg5.aidap-global.cn-beijing.volces.com
export PGUSER=postgres
export PGDATABASE=postgres

# 执行迁移脚本
./docs/migration/migrate_data.sh
```

### 2.2 验证数据

- [ ] 检查 card_types 记录数
- [ ] 检查 card_keys_table 记录数
- [ ] 检查 access_logs 记录数
- [ ] 抽样验证数据完整性

---

## 三、部署到阿里云FC

### 3.1 配置环境变量

```bash
# 复制环境变量模板
cp .env.example.fc .env

# 编辑配置
vim .env
```

### 3.2 构建并推送镜像

```bash
# 登录阿里云容器镜像服务
docker login --username=your_username registry.cn-hangzhou.aliyuncs.com

# 构建镜像
docker build -t registry.cn-hangzhou.aliyuncs.com/your-repo/card-key:latest -f Dockerfile.fc .

# 推送镜像
docker push registry.cn-hangzhou.aliyuncs.com/your-repo/card-key:latest
```

### 3.3 部署函数

```bash
# 部署到FC
s deploy
```

### 3.4 配置FC环境变量

在阿里云FC控制台配置：
- SUPABASE_URL
- SUPABASE_KEY
- ADMIN_PASSWORD
- ENVIRONMENT=production

---

## 四、功能验证

### 4.1 基础功能

- [ ] 首页可访问
- [ ] 管理后台可登录
- [ ] 卡密验证功能正常
- [ ] 验证码功能正常

### 4.2 数据验证

- [ ] 现有卡密可验证
- [ ] Session Token持久化正常
- [ ] 访问日志记录正常

### 4.3 管理功能

- [ ] 卡种管理正常
- [ ] 卡密管理正常
- [ ] 统计数据正常

---

## 五、切换流量

### 5.1 最终检查

- [ ] 所有功能测试通过
- [ ] 性能满足要求
- [ ] 费用在预期范围内

### 5.2 切换域名

- [ ] 更新用户访问地址
- [ ] 或配置自定义域名

### 5.3 删除扣子项目

- [ ] 确认迁移成功
- [ ] 删除扣子托管项目
- [ ] 停止扣子计费

---

## 六、迁移后监控

### 6.1 第一周监控

- [ ] 每日检查FC调用量
- [ ] 每日检查FC费用
- [ ] 检查Supabase存储使用量
- [ ] 检查错误日志

### 6.2 费用预估

| 项目 | 预估月费用 |
|------|-----------|
| FC调用 | ~0.1元 |
| FC流量 | ~0.1元 |
| Supabase | 0元（免费版） |
| **总计** | **~0.2元** |

对比扣子托管：~470元/月 → **节省99.96%**

---

## 七、回滚方案

如果迁移出现问题：

1. 恢复扣子托管项目
2. 从备份恢复数据
3. 切换回原访问地址
4. 排查问题后重新迁移
