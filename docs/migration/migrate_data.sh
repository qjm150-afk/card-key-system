#!/bin/bash
# ============================================
# 扣子数据库 -> Supabase 数据迁移脚本
# ============================================

set -e

echo "=========================================="
echo "卡密验证系统 - 数据迁移脚本"
echo "=========================================="

# 配置变量（请根据实际情况修改）
SOURCE_HOST="${PGHOST:-}"
SOURCE_PORT="${PGPORT:-5432}"
SOURCE_USER="${PGUSER:-postgres}"
SOURCE_DB="${PGDATABASE:-postgres}"

# Supabase 配置
SUPABASE_HOST="db.xxxxx.supabase.co"  # 替换为你的Supabase主机
SUPABASE_PORT="5432"
SUPABASE_USER="postgres"
SUPABASE_DB="postgres"
SUPABASE_PASSWORD="${SUPABASE_DB_PASSWORD:-}"  # 从环境变量获取

# 备份目录
BACKUP_DIR="./migration_backup"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/backup_${TIMESTAMP}.sql"

# 创建备份目录
mkdir -p ${BACKUP_DIR}

echo ""
echo "步骤1: 导出扣子数据库..."
echo "----------------------------------------"

# 检查源数据库连接
if [ -z "$SOURCE_HOST" ]; then
    echo "错误: 请设置 PGHOST 环境变量"
    echo "示例: export PGHOST=cp-magic-vapor-xxxxx.pg5.aidap-global.cn-beijing.volces.com"
    exit 1
fi

# 导出数据（仅数据，不含结构）
echo "正在导出数据..."
pg_dump -h ${SOURCE_HOST} \
    -p ${SOURCE_PORT} \
    -U ${SOURCE_USER} \
    -d ${SOURCE_DB} \
    --data-only \
    --no-owner \
    --no-acl \
    -v \
    -f ${BACKUP_FILE}

if [ $? -eq 0 ]; then
    echo "✅ 数据导出成功: ${BACKUP_FILE}"
    echo "   文件大小: $(ls -lh ${BACKUP_FILE} | awk '{print $5}')"
else
    echo "❌ 数据导出失败"
    exit 1
fi

echo ""
echo "步骤2: 检查Supabase连接..."
echo "----------------------------------------"

if [ -z "$SUPABASE_PASSWORD" ]; then
    echo "错误: 请设置 SUPABASE_DB_PASSWORD 环境变量"
    exit 1
fi

# 测试连接
PGPASSWORD=${SUPABASE_PASSWORD} psql \
    -h ${SUPABASE_HOST} \
    -p ${SUPABASE_PORT} \
    -U ${SUPABASE_USER} \
    -d ${SUPABASE_DB} \
    -c "SELECT 1;" > /dev/null 2>&1

if [ $? -eq 0 ]; then
    echo "✅ Supabase 连接成功"
else
    echo "❌ Supabase 连接失败，请检查配置"
    exit 1
fi

echo ""
echo "步骤3: 创建Supabase表结构..."
echo "----------------------------------------"

# 执行表结构脚本
PGPASSWORD=${SUPABASE_PASSWORD} psql \
    -h ${SUPABASE_HOST} \
    -p ${SUPABASE_PORT} \
    -U ${SUPABASE_USER} \
    -d ${SUPABASE_DB} \
    -f ./docs/migration/supabase_schema.sql

if [ $? -eq 0 ]; then
    echo "✅ 表结构创建成功"
else
    echo "❌ 表结构创建失败"
    exit 1
fi

echo ""
echo "步骤4: 导入数据到Supabase..."
echo "----------------------------------------"

# 导入数据
PGPASSWORD=${SUPABASE_PASSWORD} psql \
    -h ${SUPABASE_HOST} \
    -p ${SUPABASE_PORT} \
    -U ${SUPABASE_USER} \
    -d ${SUPABASE_DB} \
    -f ${BACKUP_FILE}

if [ $? -eq 0 ]; then
    echo "✅ 数据导入成功"
else
    echo "❌ 数据导入失败"
    exit 1
fi

echo ""
echo "步骤5: 验证数据完整性..."
echo "----------------------------------------"

# 验证各表记录数
for table in card_types card_keys_table access_logs session_tokens admin_settings; do
    count=$(PGPASSWORD=${SUPABASE_PASSWORD} psql \
        -h ${SUPABASE_HOST} \
        -p ${SUPABASE_PORT} \
        -U ${SUPABASE_USER} \
        -d ${SUPABASE_DB} \
        -t \
        -c "SELECT COUNT(*) FROM ${table};")
    
    echo "   ${table}: $(echo ${count} | tr -d ' ') 条记录"
done

echo ""
echo "=========================================="
echo "✅ 数据迁移完成！"
echo "=========================================="
echo ""
echo "下一步："
echo "1. 更新环境变量 SUPABASE_URL 和 SUPABASE_KEY"
echo "2. 部署到阿里云FC"
echo "3. 测试验证功能"
echo ""
