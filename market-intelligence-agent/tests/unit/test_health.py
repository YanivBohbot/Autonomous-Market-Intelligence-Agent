import re

from fastapi.testclient import TestClient
from app.api.server import app

client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    # Version comes from installed package metadata; don't hard-code an exact
    # value (it drifts whenever pyproject is bumped without a reinstall). Just
    # assert the field is present and looks like a semver string.
    assert isinstance(body["version"], str)
    assert re.match(r"^\d+\.\d+\.\d+", body["version"]), body["version"]
