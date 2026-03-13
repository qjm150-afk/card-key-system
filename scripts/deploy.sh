#!/bin/bash
#
# 标准化部署脚本
# 用于卡密验证系统的安全部署
#
# 使用方法：
#   ./scripts/deploy.sh           # 完整部署流程
#   ./scripts/deploy.sh --skip-backup  # 跳过备份（不推荐）
#

set -e  # 遇到错误立即退出

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 项目根目录
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${PROJECT_ROOT}/backups"
LOG_FILE="/app/work/logs/bypass/deploy.log"

# 解析参数
SKIP_BACKUP=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-backup)
            SKIP_BACKUP=true
            shift
            ;;
        *)
            echo "未知参数: $1"
            exit 1
            ;;
    esac
done

# 日志函数
log() {
    local level=$1
    local message=$2
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "${timestamp} [${level}] ${message}" | tee -a "${LOG_FILE}"
}

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
    log "INFO" "$1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
    log "SUCCESS" "$1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
    log "WARNING" "$1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
    log "ERROR" "$1"
}

# 分隔线
separator() {
    echo "============================================================"
}

# 获取当前时间戳
get_timestamp() {
    date '+%Y%m%d_%H%M%S'
}

# 主流程
main() {
    local start_time=$(date +%s)
    
    separator
    echo -e "${GREEN}🚀 卡密验证系统 - 标准化部署流程${NC}"
    separator
    echo ""
    
    cd "${PROJECT_ROOT}"
    
    # ============================================
    # 第一阶段：准备工作
    # ============================================
    echo -e "${BLUE}📋 第一阶段：准备工作${NC}"
    echo ""
    
    log_info "项目目录: ${PROJECT_ROOT}"
    log_info "开始时间: $(date '+%Y-%m-%d %H:%M:%S')"
    echo ""
    
    # ============================================
    # 第二阶段：数据备份 ⭐
    # ============================================
    echo -e "${BLUE}📦 第二阶段：数据备份${NC}"
    echo ""
    
    if [ "$SKIP_BACKUP" = true ]; then
        log_warning "已跳过数据备份（使用了 --skip-backup 参数）"
    else
        log_info "执行数据备份..."
        
        if python scripts/backup_data.py; then
            # 获取最新的备份文件
            LATEST_BACKUP=$(ls -t "${BACKUP_DIR}"/backup_*.json 2>/dev/null | head -1)
            if [ -n "$LATEST_BACKUP" ]; then
                log_success "数据备份完成: ${LATEST_BACKUP}"
            else
                log_error "未找到备份文件"
                exit 1
            fi
        else
            log_error "数据备份失败，中止部署"
            exit 1
        fi
    fi
    echo ""
    
    # ============================================
    # 第三阶段：构建
    # ============================================
    echo -e "${BLUE}🔨 第三阶段：构建${NC}"
    echo ""
    
    log_info "执行构建命令..."
    
    if coze build; then
        log_success "构建完成"
    else
        log_error "构建失败，中止部署"
        exit 1
    fi
    echo ""
    
    # ============================================
    # 第四阶段：服务验证
    # ============================================
    echo -e "${BLUE}✅ 第四阶段：服务验证${NC}"
    echo ""
    
    log_info "检查服务状态..."
    
    # 等待服务启动
    sleep 2
    
    # 检查端口
    if ss -tuln 2>/dev/null | grep -E ':5000[[:space:]]' | grep -q LISTEN; then
        log_success "端口 5000 服务运行正常"
    else
        log_warning "端口 5000 未监听，可能需要手动启动服务"
    fi
    
    # 测试 API
    log_info "测试 API 接口..."
    
    # 测试在线用户接口
    ONLINE_TEST=$(curl -s http://localhost:5000/api/online-users 2>/dev/null)
    if echo "$ONLINE_TEST" | grep -q '"success":true'; then
        log_success "API 接口测试通过"
    else
        log_warning "API 接口测试失败，请检查服务状态"
    fi
    
    # 测试首页
    INDEX_TEST=$(curl -s http://localhost:5000/ 2>/dev/null | head -c 100)
    if echo "$INDEX_TEST" | grep -q "DOCTYPE"; then
        log_success "首页访问正常"
    else
        log_warning "首页访问异常，请检查"
    fi
    echo ""
    
    # ============================================
    # 第五阶段：日志检查
    # ============================================
    echo -e "${BLUE}📝 第五阶段：日志检查${NC}"
    echo ""
    
    # 检查是否有严重错误
    ERROR_COUNT=$(tail -n 50 /app/work/logs/bypass/app.log 2>/dev/null | grep -ciE "error|exception|traceback" | head -1 || echo "0")
    
    if [ "$ERROR_COUNT" -gt 0 ]; then
        log_warning "发现 ${ERROR_COUNT} 条错误日志，请检查"
        tail -n 10 /app/work/logs/bypass/app.log 2>/dev/null | grep -iE "error|exception"
    else
        log_success "无严重错误日志"
    fi
    echo ""
    
    # ============================================
    # 完成
    # ============================================
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    
    separator
    echo -e "${GREEN}🎉 部署完成！${NC}"
    separator
    echo ""
    echo "📊 部署统计："
    echo "   - 总耗时: ${duration} 秒"
    echo "   - 备份目录: ${BACKUP_DIR}"
    echo ""
    echo "🔗 访问地址："
    echo "   - 用户登录页: http://localhost:5000/"
    echo "   - 管理后台:   http://localhost:5000/admin"
    echo ""
    
    # 记录部署日志
    log_success "部署流程完成，耗时 ${duration} 秒"
}

# 执行主流程
main
