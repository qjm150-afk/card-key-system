-- 添加链接名称字段
-- 执行时间：2026-03-13
-- 说明：为飞书链接添加中文名称备注

ALTER TABLE card_keys_table 
ADD COLUMN IF NOT EXISTS link_name VARCHAR(100) DEFAULT '' 
COMMENT '链接名称';

-- 更新索引（可选）
-- CREATE INDEX IF NOT EXISTS idx_card_keys_link_name ON card_keys_table(link_name);
