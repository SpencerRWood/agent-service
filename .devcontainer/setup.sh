#!/usr/bin/env bash
set -euo pipefail

cd /workspace

# ------------------------------------------------
# Install uv
# ------------------------------------------------

curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.cargo/bin:$PATH"

# ------------------------------------------------
# Install promtail
# ------------------------------------------------

PROMTAIL_VERSION="3.2.1"
ARCH="$(dpkg --print-architecture)"

case "$ARCH" in
  amd64) PROMTAIL_ARCH="amd64" ;;
  arm64) PROMTAIL_ARCH="arm64" ;;
  *)
    echo "Unsupported architecture for promtail: $ARCH"
    exit 1
    ;;
esac

mkdir -p "$HOME/.local/bin"
curl -fsSL \
  "https://github.com/grafana/loki/releases/download/v${PROMTAIL_VERSION}/promtail-linux-${PROMTAIL_ARCH}.zip" \
  -o /tmp/promtail.zip
python3 - <<'PY'
from pathlib import Path
from zipfile import ZipFile

target = Path.home() / ".local" / "bin"
target.mkdir(parents=True, exist_ok=True)
with ZipFile("/tmp/promtail.zip") as archive:
    binary = next(name for name in archive.namelist() if name.startswith("promtail-linux-"))
    archive.extract(binary, path=target)
    extracted = target / binary
    final_path = target / "promtail"
    if final_path.exists():
        final_path.unlink()
    extracted.rename(final_path)
    final_path.chmod(0o755)
PY
rm -f /tmp/promtail.zip

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
