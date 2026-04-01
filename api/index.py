"""
Vercel Serverless Function 入口
将 FastAPI 应用包装为 Vercel 兼容的 handler
"""

import sys
import os

# 添加项目根目录到 Python 路径
_root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_src_dir = os.path.join(_root_dir, 'src')
for _p in [_root_dir, _src_dir]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 设置静态文件目录（Vercel 环境）
# Vercel 的静态文件通过 public/ 目录提供，这里设置 src/static 作为备选
os.environ.setdefault('STATIC_DIR', os.path.join(_src_dir, 'static'))

# 导入 FastAPI 应用
from src.main import app

# Vercel 需要的 handler
handler = app
