-- ============================================
-- 飞书链接泄露检测功能迁移脚本
-- 执行环境：Supabase 控制台 SQL Editor
-- 功能：创建飞书访问记录表，用于对比分析链接泄露
-- ============================================

-- ========================================
-- STEP 1: 创建飞书访问记录表
-- ========================================

CREATE TABLE IF NOT EXISTS feishu_access_records (
    id SERIAL PRIMARY KEY,
    
    -- 关联信息
    link_name VARCHAR(200),          -- 链接名称（对应卡密的link_name）
    feishu_url TEXT,                 -- 飞书链接URL
    
    -- 访问信息
    visitor_name VARCHAR(200),       -- 访问者姓名
    access_time TIMESTAMP WITH TIME ZONE,  -- 访问时间
    access_count INTEGER DEFAULT 1,  -- 访问次数
    
    -- 来源信息
    source VARCHAR(50) DEFAULT 'manual',  -- 来源：manual=手动录入, import=批量导入
    notes TEXT,                      -- 备注
    
    -- 时间戳
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE
);

-- 创建索引
CREATE INDEX IF NOT EXISTS ix_feishu_access_records_link_name ON feishu_access_records(link_name);
CREATE INDEX IF NOT EXISTS ix_feishu_access_records_feishu_url ON feishu_access_records(feishu_url);
CREATE INDEX IF NOT EXISTS ix_feishu_access_records_visitor_name ON feishu_access_records(visitor_name);
CREATE INDEX IF NOT EXISTS ix_feishu_access_records_access_time ON feishu_access_records(access_time);

-- 添加注释
COMMENT ON TABLE feishu_access_records IS '飞书访问记录表 - 手动录入的飞书文档访问记录';
COMMENT ON COLUMN feishu_access_records.link_name IS '链接名称（对应卡密的link_name）';
COMMENT ON COLUMN feishu_access_records.feishu_url IS '飞书链接URL';
COMMENT ON COLUMN feishu_access_records.visitor_name IS '访问者姓名';
COMMENT ON COLUMN feishu_access_records.access_time IS '访问时间';
COMMENT ON COLUMN feishu_access_records.access_count IS '访问次数';
COMMENT ON COLUMN feishu_access_records.source IS '来源：manual=手动录入, import=批量导入';
COMMENT ON COLUMN feishu_access_records.notes IS '备注信息';

-- ========================================
-- STEP 2: 创建泄露检测结果表（可选，用于保存检测结果）
-- ========================================

CREATE TABLE IF NOT EXISTS leak_detection_results (
    id SERIAL PRIMARY KEY,
    
    -- 关联信息
    link_name VARCHAR(200),
    feishu_url TEXT,
    
    -- 检测结果
    total_visitors INTEGER DEFAULT 0,        -- 飞书记录的访问者总数
    system_visitors INTEGER DEFAULT 0,       -- 系统记录的访问者总数
    unknown_visitors INTEGER DEFAULT 0,      -- 未知访问者数量（疑似泄露）
    leak_risk_level VARCHAR(20),             -- 泄露风险等级：low, medium, high
    
    -- 详细信息
    unknown_visitor_names TEXT,              -- 未知访问者姓名列表（JSON数组）
    
    -- 时间戳
    detected_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

-- 创建索引
CREATE INDEX IF NOT EXISTS ix_leak_detection_link_name ON leak_detection_results(link_name);
CREATE INDEX IF NOT EXISTS ix_leak_detection_detected_at ON leak_detection_results(detected_at);

-- 添加注释
COMMENT ON TABLE leak_detection_results IS '泄露检测结果表 - 保存每次检测的结果';
COMMENT ON COLUMN leak_detection_results.total_visitors IS '飞书记录的访问者总数';
COMMENT ON COLUMN leak_detection_results.system_visitors IS '系统记录的访问者总数';
COMMENT ON COLUMN leak_detection_results.unknown_visitors IS '未知访问者数量（疑似泄露）';
COMMENT ON COLUMN leak_detection_results.leak_risk_level IS '泄露风险等级：low=低风险, medium=中风险, high=高风险';
COMMENT ON COLUMN leak_detection_results.unknown_visitor_names IS '未知访问者姓名列表（JSON数组格式）';

-- ========================================
-- 验证
-- ========================================

-- 检查表是否创建成功
SELECT 'feishu_access_records 表创建成功' as result FROM feishu_access_records LIMIT 1;
SELECT 'leak_detection_results 表创建成功' as result FROM leak_detection_results LIMIT 1;

-- 输出完成信息
SELECT '迁移完成！飞书访问记录表已创建。' as status;
