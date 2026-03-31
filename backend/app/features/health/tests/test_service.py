from app.features.health.service import HealthService


def test_service_get():
    service = HealthService()

    result = service.get()

    assert result == {"status": "ok"}
