import pytest

from fedcloud_jupyterhub.client import (
    JupyterHubClient,
    JupyterHubClientError,
    add_token,
    get_user,
    start_server,
)


def test_get_user_requires_endpoint_and_token():
    with pytest.raises(JupyterHubClientError, match="hub_api_endpoint"):
        get_user(token="token")


def test_start_server_validates_server_name_before_request():
    with pytest.raises(JupyterHubClientError, match="server"):
        start_server(hub_api_endpoint="https://hub.example/api/", token="token")


def test_start_server_validates_options_json_before_request():
    with pytest.raises(JupyterHubClientError, match="valid JSON"):
        start_server(
            hub_api_endpoint="https://hub.example/api/",
            token="token",
            server="demo",
            options="{broken",
        )


def test_add_token_rejects_role_and_scope_together():
    with pytest.raises(JupyterHubClientError, match="role"):
        add_token(
            hub_api_endpoint="https://hub.example/api/",
            token="token",
            role=("user",),
            scope=("inherit",),
        )


def test_client_wrapper_stores_common_context(monkeypatch):
    calls = []

    def fake_get_servers(**kwargs):
        calls.append(kwargs)
        return {}

    monkeypatch.setattr("fedcloud_jupyterhub.client.get_servers", fake_get_servers)

    client = JupyterHubClient("https://hub.example/api/", "token", user="alice")

    assert client.get_servers(include_stopped_servers=True) == {}
    assert calls == [
        {
            "hub_api_endpoint": "https://hub.example/api/",
            "token": "token",
            "user": "alice",
            "include_stopped_servers": True,
        }
    ]
