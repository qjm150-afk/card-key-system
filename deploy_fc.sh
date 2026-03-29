#!/bin/bash
# ============================================
# 阿里云 FC 部署脚本
# ============================================

set -e

# 配置信息
REGISTRY="crpi-58hj1qq38r30k6ax.cn-hangzhou.personal.cr.aliyuncs.com"
NAMESPACE="card-key"
IMAGE_NAME="card-key-api"
IMAGE_TAG="latest"
FULL_IMAGE="${REGISTRY}/${NAMESPACE}/${IMAGE_NAME}:${IMAGE_TAG}"

# 阿里云 FC 配置
REGION="cn-hangzhou"
SERVICE_NAME="card-key-service"
FUNCTION_NAME="card-key-api"

echo "============================================"
echo "卡密验证系统 - 阿里云 FC 部署"
echo "============================================"
echo ""

# 1. 构建 Docker 镜像
echo "📦 构建 Docker 镜像..."
docker build -t ${FULL_IMAGE} -f Dockerfile .

if [ $? -ne 0 ]; then
    echo "❌ 构建失败"
    exit 1
fi
echo "✅ 构建成功"
echo ""

# 2. 登录阿里云镜像仓库
echo "🔐 登录阿里云镜像仓库..."
echo "请输入 Registry 密码："
docker login --username=aliyun3949702043 ${REGISTRY}

if [ $? -ne 0 ]; then
    echo "❌ 登录失败"
    exit 1
fi
echo "✅ 登录成功"
echo ""

# 3. 推送镜像
echo "📤 推送镜像到阿里云..."
docker push ${FULL_IMAGE}

if [ $? -ne 0 ]; then
    echo "❌ 推送失败"
    exit 1
fi
echo "✅ 推送成功"
echo ""

# 4. 部署到 FC
echo "🚀 部署到函数计算..."
echo ""
echo "请手动在阿里云 FC 控制台创建函数："
echo "1. 访问: https://fcnext.console.aliyun.com/"
echo "2. 选择区域: 华东1（杭州）"
echo "3. 创建服务: ${SERVICE_NAME}"
echo "4. 创建函数:"
echo "   - 函数类型: Web 函数"
echo "   - 运行环境: Custom Runtime"
echo "   - 镜像地址: ${FULL_IMAGE}"
echo "   - 端口: 5000"
echo "   - 内存: 512MB"
echo "   - 超时: 60秒"
echo ""
echo "环境变量配置:"
echo "  COZE_SUPABASE_URL=https://ktivyspgzpxrawjtmkck.supabase.co"
echo "  COZE_SUPABASE_ANON_KEY=<your-key>"
echo "  ADMIN_PASSWORD=QJM150"
echo ""
echo "============================================"
echo "部署脚本执行完成！"
echo "============================================"
