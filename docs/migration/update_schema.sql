-- ============================================
-- 更新 Supabase 表结构以匹配扣子数据库
-- ============================================

-- 1. card_types 表添加缺失字段
ALTER TABLE card_types ADD COLUMN IF NOT EXISTS blur_level INTEGER DEFAULT 8;

-- 2. card_keys_table 表添加缺失字段
ALTER TABLE card_keys_table ADD COLUMN IF NOT EXISTS max_uses INTEGER DEFAULT 1;
ALTER TABLE card_keys_table ADD COLUMN IF NOT EXISTS use_count INTEGER DEFAULT 0;
ALTER TABLE card_keys_table ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP;

-- 3. 临时禁用 RLS 以便导入数据
ALTER TABLE card_types DISABLE ROW LEVEL SECURITY;
ALTER TABLE card_keys_table DISABLE ROW LEVEL SECURITY;
ALTER TABLE admin_settings DISABLE ROW LEVEL SECURITY;
ALTER TABLE access_logs DISABLE ROW LEVEL SECURITY;
ALTER TABLE session_tokens DISABLE ROW LEVEL SECURITY;

-- 完成
SELECT 'Table structure updated successfully!' as message;
