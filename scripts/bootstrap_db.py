from __future__ import annotations

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from provision_db import main as provision_db  # noqa: E402


def main() -> None:
    provision_db()

    alembic_config = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))

    command.upgrade(alembic_config, "head")
    print("Migrations applied.")


if __name__ == "__main__":
    main()
