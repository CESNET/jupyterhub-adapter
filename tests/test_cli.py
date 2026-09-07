"""Tests for the optional Click wrapper around the object-oriented library API."""

from click.testing import CliRunner

import fedcloud_jupyterhub.cli as cli_module
from fedcloud_jupyterhub import JupyterHubAPIError
from fedcloud_jupyterhub.cli import jupyterhub


def test_cli_group_loads():
    result = CliRunner().invoke(jupyterhub, ["--help"])

    assert result.exit_code == 0
    assert "Communicate with JupyterHub" in result.output
    assert "server" in result.output
    assert "token" in result.output


def test_cli_reports_library_validation_errors():
    result = CliRunner().invoke(
        jupyterhub,
        [
            "server",
            "start",
            "--hub-api-endpoint",
            "https://hub.example/hub/api/",
            "--token",
            "token",
            "--server",
            "demo",
            "--options",
            "{broken",
        ],
    )

    assert result.exit_code != 0
    assert "valid JSON" in result.output


def test_cli_translates_api_exception_into_click_error(monkeypatch):
    def fail(self, **kwargs):
        raise JupyterHubAPIError(500, "Hub unavailable")

    monkeypatch.setattr(cli_module.JupyterHubClient, "get_user", fail)

    result = CliRunner().invoke(
        jupyterhub,
        [
            "user",
            "show",
            "--hub-api-endpoint",
            "https://hub.example/hub/api/",
            "--token",
            "token",
        ],
    )

    assert result.exit_code == 1
    assert "Hub unavailable" in result.output


def test_cli_creates_client_from_common_connection_parameters(monkeypatch):
    created = []

    class FakeClient:
        def __init__(self, hub_api_endpoint, token, user=None):
            created.append(
                {
                    "hub_api_endpoint": hub_api_endpoint,
                    "token": token,
                    "user": user,
                }
            )

        def get_servers(self, **kwargs):
            return {}

    monkeypatch.setattr(cli_module, "JupyterHubClient", FakeClient)

    result = CliRunner().invoke(
        jupyterhub,
        [
            "server",
            "list",
            "--hub-api-endpoint",
            "https://hub.example/hub/api/",
            "--token",
            "token",
            "--user",
            "alice",
        ],
    )

    assert result.exit_code == 0
    assert created == [
        {
            "hub_api_endpoint": "https://hub.example/hub/api/",
            "token": "token",
            "user": "alice",
        }
    ]


def test_path_add_maps_cli_type_option_to_client_method(monkeypatch):
    received = []

    def fake_add_path(self, **kwargs):
        received.append(kwargs)
        return {"path": "work/new", "type": "directory"}

    monkeypatch.setattr(cli_module.JupyterHubClient, "add_path", fake_add_path)

    result = CliRunner().invoke(
        jupyterhub,
        [
            "path",
            "add",
            "--hub-api-endpoint",
            "https://hub.example/hub/api/",
            "--token",
            "token",
            "--server",
            "demo",
            "--destination",
            "work",
            "--type",
            "directory",
        ],
    )

    assert result.exit_code == 0
    assert received[0]["path_type"] == "directory"
    assert "type" not in received[0]
    assert "hub_api_endpoint" not in received[0]
    assert "token" not in received[0]


def test_remove_all_cli_flag_maps_directly_to_client_method(monkeypatch):
    received = []

    def fake_remove_shared_access(self, **kwargs):
        received.append(kwargs)
        return None

    monkeypatch.setattr(
        cli_module.JupyterHubClient,
        "remove_shared_access",
        fake_remove_shared_access,
    )

    result = CliRunner().invoke(
        jupyterhub,
        [
            "sharing",
            "rm",
            "--hub-api-endpoint",
            "https://hub.example/hub/api/",
            "--token",
            "token",
            "--server",
            "demo",
            "--all",
        ],
    )

    assert result.exit_code == 0
    assert received[0]["remove_all"] is True
