-- 卡种管理功能迁移脚本
-- 在 Supabase 控制台的 SQL Editor 中执行
-- 执行时间：约 1-2 分钟

-- ========================================
-- STEP 1: 创建卡种表
-- ========================================

CREATE TABLE IF NOT EXISTS card_types (
    id SERIAL PRIMARY KEY,
    
    -- 基础信息
    name VARCHAR(200) NOT NULL,
    
    -- 预览设置
    preview_image TEXT,
    preview_enabled BOOLEAN DEFAULT FALSE NOT NULL,
    blur_level INTEGER DEFAULT 8 NOT NULL,
    
    -- 状态
    status INTEGER DEFAULT 1 NOT NULL,
    deleted_at TIMESTAMP WITH TIME ZONE,
    
    -- 时间戳
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE
);

-- 创建索引
CREATE INDEX IF NOT EXISTS ix_card_types_name ON card_types(name);
CREATE INDEX IF NOT EXISTS ix_card_types_status ON card_types(status);

-- 添加注释
COMMENT ON TABLE card_types IS '卡种表 - 卡密分组管理';
COMMENT ON COLUMN card_types.name IS '卡种名称';
COMMENT ON COLUMN card_types.preview_image IS '预览截图URL';
COMMENT ON COLUMN card_types.preview_enabled IS '是否启用预览';
COMMENT ON COLUMN card_types.blur_level IS '模糊程度(px)';
COMMENT ON COLUMN card_types.status IS '状态: 1=有效, 0=无效';
COMMENT ON COLUMN card_types.deleted_at IS '软删除时间';

-- ========================================
-- STEP 2: 为卡密表添加卡种关联字段
-- ========================================

-- 添加 card_type_id 字段
ALTER TABLE card_keys_table 
ADD COLUMN IF NOT EXISTS card_type_id INTEGER REFERENCES card_types(id);

-- 创建索引
CREATE INDEX IF NOT EXISTS ix_card_keys_card_type_id ON card_keys_table(card_type_id);

-- 添加注释
COMMENT ON COLUMN card_keys_table.card_type_id IS '关联的卡种ID';

-- ========================================
-- STEP 3: 创建预览图片表（可选）
-- ========================================

CREATE TABLE IF NOT EXISTS preview_images (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    url TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_preview_images_name ON preview_images(name);

-- ========================================
-- 验证
-- ========================================

-- 检查表是否创建成功
SELECT 'card_types 表创建成功' as result FROM card_types LIMIT 1;

-- 检查字段是否添加成功
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'card_keys_table' AND column_name = 'card_type_id';

-- 输出完成信息
SELECT '迁移完成！' as status;
