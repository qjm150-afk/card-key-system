-- 数据分析功能数据库迁移脚本
-- 为 access_logs 表添加行为数据采集字段
-- 请在 Supabase 控制台的 SQL Editor 中执行此脚本

-- 添加访问日期字段（用于按日期统计）
ALTER TABLE access_logs 
ADD COLUMN IF NOT EXISTS access_date DATE;

-- 添加访问小时字段（用于时段分析）
ALTER TABLE access_logs 
ADD COLUMN IF NOT EXISTS access_hour INTEGER;

-- 添加设备类型字段（用于设备分布分析）
ALTER TABLE access_logs 
ADD COLUMN IF NOT EXISTS device_type VARCHAR(20);

-- 添加IP省份字段（用于地域分布分析，已脱敏）
ALTER TABLE access_logs 
ADD COLUMN IF NOT EXISTS ip_province VARCHAR(50);

-- 添加是否首次访问字段（用于新用户分析）
ALTER TABLE access_logs 
ADD COLUMN IF NOT EXISTS is_first_access BOOLEAN DEFAULT FALSE;

-- 添加销售渠道字段（用于渠道效果分析）
ALTER TABLE access_logs 
ADD COLUMN IF NOT EXISTS sales_channel VARCHAR(100);

-- 添加会话停留时长字段（用于内容效果分析）
ALTER TABLE access_logs 
ADD COLUMN IF NOT EXISTS session_duration INTEGER;

-- 添加内容加载状态字段（用于监控内容可用性）
ALTER TABLE access_logs 
ADD COLUMN IF NOT EXISTS content_loaded BOOLEAN;

-- 创建索引以提升查询性能
CREATE INDEX IF NOT EXISTS idx_access_logs_access_date ON access_logs(access_date);
CREATE INDEX IF NOT EXISTS idx_access_logs_access_hour ON access_logs(access_hour);
CREATE INDEX IF NOT EXISTS idx_access_logs_device_type ON access_logs(device_type);
CREATE INDEX IF NOT EXISTS idx_access_logs_ip_province ON access_logs(ip_province);
CREATE INDEX IF NOT EXISTS idx_access_logs_sales_channel ON access_logs(sales_channel);
CREATE INDEX IF NOT EXISTS idx_access_logs_is_first_access ON access_logs(is_first_access);

-- 注释
COMMENT ON COLUMN access_logs.access_date IS '访问日期，用于按日期统计';
COMMENT ON COLUMN access_logs.access_hour IS '访问小时（0-23），用于时段分析';
COMMENT ON COLUMN access_logs.device_type IS '设备类型：PC/Mobile/Tablet';
COMMENT ON COLUMN access_logs.ip_province IS 'IP所属省份（已脱敏），用于地域分布分析';
COMMENT ON COLUMN access_logs.is_first_access IS '是否首次访问该卡密';
COMMENT ON COLUMN access_logs.sales_channel IS '销售渠道';
COMMENT ON COLUMN access_logs.session_duration IS '会话停留时长（秒）';
COMMENT ON COLUMN access_logs.content_loaded IS '内容是否成功加载';

-- 为 card_keys_table 添加销售渠道字段（如果不存在）
ALTER TABLE card_keys_table 
ADD COLUMN IF NOT EXISTS sales_channel VARCHAR(100);

COMMENT ON COLUMN card_keys_table.sales_channel IS '销售渠道';
