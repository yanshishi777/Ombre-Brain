"""Real HTTP coverage for the management paths used by a desktop host.

The suite is intentionally one ordered flow because it performs first-run
password setup in an isolated Docker volume. It never targets a user vault.
"""

import os
from urllib.parse import urlsplit

import httpx
import pytest


def _configured_base_url() -> str:
    explicit = os.environ.get("OMBRE_DOCKER_WEB_BASE_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    mcp_url = os.environ.get("OMBRE_DOCKER_INTEGRATION_URL", "").strip()
    if not mcp_url:
        return ""
    parsed = urlsplit(mcp_url)
    return f"{parsed.scheme}://{parsed.netloc}"


BASE_URL = _configured_base_url()
pytestmark = pytest.mark.skipif(
    not BASE_URL,
    reason="Docker Web integration service is not configured",
)


def test_desktop_management_api_first_run_and_authenticated_flow():
    with httpx.Client(base_url=BASE_URL, timeout=60.0) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        version = client.get("/api/version")
        assert version.status_code == 200
        assert version.json()["version"]

        update_info = client.get("/api/update-info")
        assert update_info.status_code == 200
        assert update_info.json()["version"] == version.json()["version"]

        auth_before = client.get("/auth/status")
        assert auth_before.status_code == 200
        assert auth_before.json() == {
            "authenticated": False,
            "setup_needed": True,
        }

        protected_before = client.get("/api/config")
        assert protected_before.status_code == 401

        weak_password = client.post("/auth/setup", json={"password": "123"})
        assert weak_password.status_code == 400

        setup = client.post(
            "/auth/setup",
            json={"password": "docker-audit-password"},
        )
        assert setup.status_code == 200
        assert setup.json()["ok"] is True
        assert client.cookies.get("ombre_session")

        auth_after = client.get("/auth/status")
        assert auth_after.json() == {
            "authenticated": True,
            "setup_needed": False,
        }

        config = client.get("/api/config")
        assert config.status_code == 200
        config_payload = config.json()
        assert config_payload["transport"] == "streamable-http"
        assert config_payload["mcp_require_auth"] is False
        assert "api_key" not in config_payload.get("dehydration", {})
        assert "api_key" not in config_payload.get("embedding", {})

        invalid_update = client.post(
            "/api/config",
            json={"embedding": "not-an-object"},
        )
        assert invalid_update.status_code == 400

        config_update = client.post(
            "/api/config",
            json={"surfacing": {"breath_max_results": 11}, "persist": False},
        )
        assert config_update.status_code == 200
        assert "surfacing.breath_max_results" in config_update.json()["updated"]
        assert client.get("/api/config").json()["surfacing"]["breath_max_results"] == 11

        status = client.get("/api/status")
        assert status.status_code == 200
        assert status.json()["version"] == version.json()["version"]
        assert status.json()["decay_engine"] == "running"

        diagnostics = client.get("/api/system/diagnostics")
        assert diagnostics.status_code == 200
        assert "checks" in diagnostics.json()

        invalid_transport = client.post(
            "/api/transport",
            json={"transport": "not-a-transport"},
        )
        assert invalid_transport.status_code == 400

        unchanged_transport = client.post(
            "/api/transport",
            json={"transport": "streamable-http"},
        )
        assert unchanged_transport.status_code == 200
        assert unchanged_transport.json()["restarting"] is False

        logout = client.post("/auth/logout")
        assert logout.status_code == 200
        assert client.get("/api/config").status_code == 401
