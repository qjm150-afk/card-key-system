#!/bin/bash
set -Eeuo pipefail

cd "${COZE_WORKSPACE_PATH:-$(pwd)}"

echo "Installing dependencies..."
pip install -r requirements.txt -q

echo "Starting development server on port 5000..."
python -m uvicorn src.main:app --host 0.0.0.0 --port 5000 --reload
