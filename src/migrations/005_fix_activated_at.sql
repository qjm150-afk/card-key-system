-- ============================================
-- 修复已激活卡密的 activated_at 字段
-- 执行环境：生产环境 Supabase
-- 问题原因：状态判断逻辑从 devices 改为 activated_at
-- ============================================

-- 1. 先查看需要修复的卡密数量
SELECT 
    COUNT(*) as need_fix_count,
    COUNT(CASE WHEN devices != '[]' AND devices IS NOT NULL THEN 1 END) as has_devices_count
FROM card_keys_table 
WHERE activated_at IS NULL 
  AND devices IS NOT NULL 
  AND devices != '[]';

-- 2. 执行修复：为有设备绑定但 activated_at 为空的卡密设置激活时间
-- 使用 last_used_at 或 updated_at 作为激活时间
UPDATE card_keys_table 
SET activated_at = COALESCE(last_used_at, updated_at, created_at, NOW())
WHERE activated_at IS NULL 
  AND devices IS NOT NULL 
  AND devices != '[]'
  AND devices != 'null';

-- 3. 验证修复结果
SELECT 
    id,
    key_value,
    devices,
    activated_at,
    last_used_at
FROM card_keys_table 
WHERE devices IS NOT NULL 
  AND devices != '[]'
ORDER BY id
LIMIT 20;

-- 4. 统计修复后的状态
SELECT 
    COUNT(*) as total,
    COUNT(activated_at) as activated_count,
    COUNT(CASE WHEN activated_at IS NULL THEN 1 END) as not_activated_count
FROM card_keys_table;
