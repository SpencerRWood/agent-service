import os

os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("POSTGRES_DB", "agent_service_test")
os.environ.setdefault("PG_ADMIN_USER", "postgres")
os.environ.setdefault("PG_ADMIN_PASSWORD", "postgres")
os.environ.setdefault("APP_DB_USER", "postgres")
os.environ.setdefault("APP_DB_PASSWORD", "postgres")
os.environ.setdefault(
    "CONTROL_HUB_CONTRACT_PATH",
    "../control-hub/contracts/openapi/control-hub.openapi.json",
)
