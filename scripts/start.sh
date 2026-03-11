#!/bin/bash
set -Eeuo pipefail

cd "${COZE_WORKSPACE_PATH:-$(pwd)}"

echo "Starting production server on port 5000..."
uvicorn src.main:app --host 0.0.0.0 --port 5000
