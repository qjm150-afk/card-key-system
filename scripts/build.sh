#!/bin/bash
set -Eeuo pipefail

cd "${COZE_WORKSPACE_PATH:-$(pwd)}"

echo "Installing dependencies..."
pip install -r requirements.txt -q

echo "Build completed!"
