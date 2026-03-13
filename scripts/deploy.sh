#!/bin/bash
# 自动化部署脚本
# 自动执行：数据备份 → 部署前检查 → 部署

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_SCRIPT="$PROJECT_ROOT/scripts/backup_data.py"
DEPLOY_CMD="coze build && coze start"

echo "============================================"
echo "自动化部署流程"
echo "============================================"

# 步骤1：数据备份
echo ""
echo "[1/3] 执行数据备份..."
python3 "$BACKUP_SCRIPT"

if [ $? -ne 0 ]; then
    echo "❌ 备份失败，终止部署！"
    exit 1
fi

echo ""
echo "✅ 备份完成"

# 步骤2：部署前确认
echo ""
echo "[2/3] 部署前确认"
echo ""
echo "检查清单："
echo "  - 数据备份：✅ 已完成"
echo "  - 本地测试：请确认已通过"
echo "  - 代码检查：请确认无禁止操作"
echo ""

read -p "确认部署？(y/n): " confirm
if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
    echo "已取消部署"
    exit 0
fi

# 步骤3：执行部署
echo ""
echo "[3/3] 执行部署..."
cd "$PROJECT_ROOT"

# 构建项目
echo "构建项目..."
coze build

if [ $? -ne 0 ]; then
    echo "❌ 构建失败！"
    exit 1
fi

# 启动服务
echo "启动服务..."
coze start

echo ""
echo "============================================"
echo "✅ 部署完成！"
echo "============================================"
echo ""
echo "如遇问题，可执行以下命令恢复数据："
echo "  python scripts/restore_data.py --latest"
