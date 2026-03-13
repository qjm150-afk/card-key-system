-- 添加会话ID字段迁移脚本
-- 用于支持完整的会话追踪功能
-- 
-- SQLite 版本：直接执行 ALTER TABLE
-- Supabase 版本：请在 Supabase 控制台的 SQL Editor 中执行

-- 添加会话ID字段（用于唯一标识一次访问会话）
ALTER TABLE access_logs 
ADD COLUMN session_id VARCHAR(64);

-- 创建索引以提升查询性能
CREATE INDEX IF NOT EXISTS idx_access_logs_session_id ON access_logs(session_id);

-- 注释
COMMENT ON COLUMN access_logs.session_id IS '会话ID，用于唯一标识一次访问会话';
