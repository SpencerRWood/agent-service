#!/usr/bin/env bash
set -euo pipefail

cd /workspace

# ------------------------------------------------
# Install uv
# ------------------------------------------------

curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.cargo/bin:$PATH"

# ------------------------------------------------
# Backend setup
# ------------------------------------------------

cd backend

uv venv .venv --clear
source .venv/bin/activate

# Install project + dev dependencies
uv pip install -e ".[dev]"

# Install git hooks
pre-commit install
