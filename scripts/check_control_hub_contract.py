#!/usr/bin/env python3

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
def main() -> None:
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))

    from app.integrations.control_hub.contract import assert_local_contract_compatible

    assert_local_contract_compatible()


if __name__ == "__main__":
    main()
