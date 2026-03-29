#!/bin/bash
# 使用 Supabase 启动服务

cd /workspace/projects

# 设置 Supabase 环境变量
export COZE_SUPABASE_URL="https://ktivyspgzpxrawjtmkck.supabase.co"
export COZE_SUPABASE_ANON_KEY="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imt0aXZ5c3BnenB4cmF3anRta2NrIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQ3NzkwNzIsImV4cCI6MjA5MDM1NTA3Mn0.soWTMdRYmCvJTP7QbyFTniLLaY3P0XQu6bz37ItdZbA"
export SUPABASE_URL="https://ktivyspgzpxrawjtmkck.supabase.co"
export SUPABASE_KEY="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imt0aXZ5c3BnenB4cmF3anRta2NrIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQ3NzkwNzIsImV4cCI6MjA5MDM1NTA3Mn0.soWTMdRYmCvJTP7QbyFTniLLaY3P0XQu6bz37ItdZbA"
export ADMIN_PASSWORD="QJM150"

echo "启动服务..."
echo "COZE_SUPABASE_URL=$COZE_SUPABASE_URL"

# 启动服务
python -m uvicorn src.main:app --host 0.0.0.0 --port 5000
