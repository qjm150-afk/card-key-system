-- ============================================
-- Supabase 数据库表结构迁移脚本
-- 用于从扣子内置数据库迁移到 Supabase
-- ============================================

-- 设置时区
SET TIME ZONE 'Asia/Shanghai';

-- ============================================
-- 1. 卡种表
-- ============================================
CREATE TABLE IF NOT EXISTS card_types (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    status INTEGER DEFAULT 1,
    preview_image TEXT,
    preview_image_id INTEGER,
    preview_enabled BOOLEAN DEFAULT false,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    deleted_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_card_types_status ON card_types(status);
CREATE INDEX IF NOT EXISTS idx_card_types_deleted ON card_types(deleted_at);

-- ============================================
-- 2. 卡密表
-- ============================================
CREATE TABLE IF NOT EXISTS card_keys_table (
    id SERIAL PRIMARY KEY,
    key_value VARCHAR(32) UNIQUE NOT NULL,
    card_type_id INTEGER REFERENCES card_types(id),
    status INTEGER DEFAULT 1,
    sale_status VARCHAR(20) DEFAULT 'unsold',
    sales_channel VARCHAR(100),
    order_id VARCHAR(100),
    user_note TEXT,
    feishu_url TEXT,
    feishu_password VARCHAR(100),
    link_name VARCHAR(200),
    devices TEXT DEFAULT '[]',
    max_devices INTEGER DEFAULT 5,
    expire_at TIMESTAMP,
    expire_after_days INTEGER,
    activated_at TIMESTAMP,
    last_used_at TIMESTAMP,
    sold_at TIMESTAMP,
    bstudio_create_time TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_card_keys_value ON card_keys_table(key_value);
CREATE INDEX IF NOT EXISTS idx_card_keys_status ON card_keys_table(status);
CREATE INDEX IF NOT EXISTS idx_card_keys_type ON card_keys_table(card_type_id);
CREATE INDEX IF NOT EXISTS idx_card_keys_sale_status ON card_keys_table(sale_status);

-- ============================================
-- 3. 访问日志表
-- ============================================
CREATE TABLE IF NOT EXISTS access_logs (
    id SERIAL PRIMARY KEY,
    card_key_id INTEGER REFERENCES card_keys_table(id),
    key_value VARCHAR(32) NOT NULL,
    device_id VARCHAR(64),
    access_time TIMESTAMP DEFAULT NOW(),
    access_date DATE DEFAULT CURRENT_DATE,
    ip_address VARCHAR(45),
    success BOOLEAN DEFAULT false,
    message TEXT,
    user_agent TEXT,
    referrer TEXT
);

CREATE INDEX IF NOT EXISTS idx_access_logs_key ON access_logs(key_value);
CREATE INDEX IF NOT EXISTS idx_access_logs_time ON access_logs(access_time);
CREATE INDEX IF NOT EXISTS idx_access_logs_date ON access_logs(access_date);
CREATE INDEX IF NOT EXISTS idx_access_logs_success ON access_logs(success);

-- ============================================
-- 4. 会话Token表
-- ============================================
CREATE TABLE IF NOT EXISTS session_tokens (
    id SERIAL PRIMARY KEY,
    token VARCHAR(64) UNIQUE NOT NULL,
    device_id VARCHAR(64) NOT NULL,
    card_key_hash VARCHAR(64) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    expire_at TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_session_tokens_token ON session_tokens(token);
CREATE INDEX IF NOT EXISTS idx_session_tokens_device ON session_tokens(device_id);
CREATE INDEX IF NOT EXISTS idx_session_tokens_expire ON session_tokens(expire_at);

-- ============================================
-- 5. 管理员设置表
-- ============================================
CREATE TABLE IF NOT EXISTS admin_settings (
    id SERIAL PRIMARY KEY,
    key VARCHAR(100) UNIQUE NOT NULL,
    value TEXT,
    description TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 插入默认设置
INSERT INTO admin_settings (key, value, description) 
VALUES ('admin_password', '', '管理员密码')
ON CONFLICT (key) DO NOTHING;

INSERT INTO admin_settings (key, value, description) 
VALUES ('global_preview', '{"enabled": false}', '全局预览设置')
ON CONFLICT (key) DO NOTHING;

INSERT INTO admin_settings (key, value, description) 
VALUES ('docs_url', '', '文档链接')
ON CONFLICT (key) DO NOTHING;

-- ============================================
-- 6. 批量操作日志表
-- ============================================
CREATE TABLE IF NOT EXISTS batch_operation_logs (
    id SERIAL PRIMARY KEY,
    operation_type VARCHAR(50) NOT NULL,
    operator VARCHAR(100),
    affected_count INTEGER DEFAULT 0,
    details TEXT,
    operation_time TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================
-- 7. 预览图片表
-- ============================================
CREATE TABLE IF NOT EXISTS preview_images (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200),
    image_key TEXT,
    url TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================
-- 8. 链接健康检查表
-- ============================================
CREATE TABLE IF NOT EXISTS link_health_table (
    id SERIAL PRIMARY KEY,
    feishu_url TEXT NOT NULL,
    link_name VARCHAR(200),
    status VARCHAR(20),
    response_time INTEGER,
    last_check_time TIMESTAMP DEFAULT NOW(),
    error_message TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================
-- 9. 飞书访问记录表
-- ============================================
CREATE TABLE IF NOT EXISTS feishu_access_records (
    id SERIAL PRIMARY KEY,
    feishu_url TEXT NOT NULL,
    link_name VARCHAR(200),
    access_time TIMESTAMP DEFAULT NOW(),
    device_id VARCHAR(64),
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================
-- 10. 泄露检测结果表
-- ============================================
CREATE TABLE IF NOT EXISTS leak_detection_results (
    id SERIAL PRIMARY KEY,
    feishu_url TEXT NOT NULL,
    link_name VARCHAR(200),
    leak_type VARCHAR(50),
    leak_count INTEGER DEFAULT 0,
    detection_time TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================
-- 11. 健康检查表
-- ============================================
CREATE TABLE IF NOT EXISTS health_check (
    id SERIAL PRIMARY KEY,
    check_time TIMESTAMP DEFAULT NOW(),
    status VARCHAR(20),
    message TEXT
);

-- ============================================
-- 启用 Row Level Security (RLS)
-- Supabase 安全特性
-- ============================================
ALTER TABLE card_types ENABLE ROW LEVEL SECURITY;
ALTER TABLE card_keys_table ENABLE ROW LEVEL SECURITY;
ALTER TABLE access_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE session_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE admin_settings ENABLE ROW LEVEL SECURITY;

-- 创建匿名用户策略（允许公开访问）
CREATE POLICY "Allow anonymous read access" ON card_keys_table
    FOR SELECT USING (true);

CREATE POLICY "Allow anonymous insert access" ON access_logs
    FOR INSERT WITH CHECK (true);

CREATE POLICY "Allow anonymous access" ON session_tokens
    FOR ALL USING (true);

-- ============================================
-- 创建视图（可选）
-- ============================================
CREATE OR REPLACE VIEW active_cards AS
SELECT * FROM card_keys_table
WHERE status = 1
  AND (expire_at IS NULL OR expire_at > NOW())
  AND (deleted_at IS NULL OR deleted_at > NOW());

-- ============================================
-- 添加表注释
-- ============================================
COMMENT ON TABLE card_types IS '卡种配置表';
COMMENT ON TABLE card_keys_table IS '卡密主表';
COMMENT ON TABLE access_logs IS '访问日志表';
COMMENT ON TABLE session_tokens IS '会话Token表（持久化存储）';
COMMENT ON TABLE admin_settings IS '管理员设置表';

-- 完成
SELECT 'Supabase database schema created successfully!' as message;
