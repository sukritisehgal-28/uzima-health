import json
from infra.gcp.runtime import runtime_environment


def test_cloud_runtime_uses_secret_values_without_overwriting_deployment_settings(monkeypatch):
    monkeypatch.setenv("UZIMA_RUNTIME_JSON", json.dumps({"TWILIO_AUTH_TOKEN": "test-only", "TWILIO_ENABLED": "1", "USE_AWS": "0"}))
    monkeypatch.setenv("TWILIO_ENABLED", "0")
    monkeypatch.setenv("PUBLIC_HOST", "cloud.example")
    result = runtime_environment()
    assert result["TWILIO_AUTH_TOKEN"] == "test-only"
    assert result["TWILIO_ENABLED"] == "0"
    assert result["PUBLIC_HOST"] == "cloud.example"
    assert "UZIMA_RUNTIME_JSON" not in result
