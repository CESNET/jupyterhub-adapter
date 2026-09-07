"""Tests for the public Python API boundary and argument validation."""

import inspect

import pytest

import fedcloud_jupyterhub.client as client_module
from fedcloud_jupyterhub import (
    JupyterHubClient,
    JupyterHubValidationError,
    add_path,
    add_shared_access,
    add_token,
    delete_path,
    delete_token,
    exec_command,
    get_path,
    get_servers,
    get_token,
    get_user,
    list_shared_access,
    list_tokens,
    remove_shared_access,
    start_server,
    stop_server,
    upload_file,
)

PUBLIC_FUNCTIONS = (
    get_user,
    get_servers,
    start_server,
    stop_server,
    add_shared_access,
    remove_shared_access,
    list_shared_access,
    get_token,
    add_token,
    delete_token,
    list_tokens,
    get_path,
    add_path,
    delete_path,
    upload_file,
    exec_command,
)


def test_all_public_functions_use_explicit_parameters_and_annotations():
    for function in PUBLIC_FUNCTIONS:
        signature = inspect.signature(function)
        assert not any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        ), function.__name__
        assert all(
            parameter.annotation is not inspect.Signature.empty
            for parameter in signature.parameters.values()
        ), function.__name__
        assert (
            signature.return_annotation is not inspect.Signature.empty
        ), function.__name__


def test_get_user_requires_endpoint_and_token():
    with pytest.raises(TypeError):
        get_user(token="token")

    with pytest.raises(JupyterHubValidationError, match="hub_api_endpoint"):
        get_user(hub_api_endpoint=None, token="token")

    with pytest.raises(JupyterHubValidationError, match="token"):
        get_user(hub_api_endpoint="https://hub.example/hub/api/", token="")


def test_default_server_empty_name_is_valid(monkeypatch):
    monkeypatch.setattr(client_module, "_get_user_id", lambda *args, **kwargs: "alice")
    monkeypatch.setattr(client_module, "_make_request", lambda **kwargs: object())

    start_server("https://hub.example/hub/api/", "token", server="")


def test_start_server_rejects_missing_server_name():
    with pytest.raises(JupyterHubValidationError, match="server"):
        start_server(
            hub_api_endpoint="https://hub.example/hub/api/",
            token="token",
            server=None,
        )


def test_start_server_validates_options_before_network_access(monkeypatch):
    def fail_if_called(**kwargs):
        raise AssertionError("Network helper must not run for invalid public input")

    monkeypatch.setattr(client_module, "_make_request", fail_if_called)

    with pytest.raises(JupyterHubValidationError, match="valid JSON"):
        start_server(
            hub_api_endpoint="https://hub.example/hub/api/",
            token="token",
            server="demo",
            options="{broken",
        )

    with pytest.raises(JupyterHubValidationError, match="JSON object"):
        start_server(
            hub_api_endpoint="https://hub.example/hub/api/",
            token="token",
            server="demo",
            options="[1, 2]",
        )


def test_start_server_accepts_mapping_options(monkeypatch):
    calls = []
    monkeypatch.setattr(client_module, "_get_user_id", lambda *args, **kwargs: "alice")
    monkeypatch.setattr(
        client_module,
        "_make_request",
        lambda **kwargs: calls.append(kwargs) or object(),
    )

    start_server(
        "https://hub.example/hub/api/",
        "token",
        "demo",
        options={"profile": "gpu"},
    )

    assert calls[0]["data"] == {"profile": "gpu"}


def test_add_token_rejects_role_and_scope_together():
    with pytest.raises(JupyterHubValidationError, match="role"):
        add_token(
            hub_api_endpoint="https://hub.example/hub/api/",
            token="token",
            role=("user",),
            scope=("inherit",),
        )


def test_add_token_rejects_negative_expiration():
    with pytest.raises(JupyterHubValidationError, match="expiration"):
        add_token(
            hub_api_endpoint="https://hub.example/hub/api/",
            token="token",
            expiration=-1,
        )


def test_add_shared_access_requires_exactly_one_recipient():
    common = {
        "hub_api_endpoint": "https://hub.example/hub/api/",
        "token": "token",
        "server": "demo",
    }

    with pytest.raises(JupyterHubValidationError, match="Exactly one"):
        add_shared_access(**common)

    with pytest.raises(JupyterHubValidationError, match="cannot be specified"):
        add_shared_access(
            **common,
            grant_to_user="alice",
            grant_to_group="researchers",
        )


def test_remove_shared_access_requires_recipient_for_scoped_removal():
    with pytest.raises(JupyterHubValidationError, match="Exactly one"):
        remove_shared_access(
            "https://hub.example/hub/api/",
            "token",
            "demo",
            remove_all=False,
        )


def test_remove_all_does_not_require_recipient(monkeypatch):
    monkeypatch.setattr(client_module, "_get_user_id", lambda *args, **kwargs: "alice")
    monkeypatch.setattr(client_module, "_make_request", lambda **kwargs: object())

    assert (
        remove_shared_access(
            "https://hub.example/hub/api/",
            "token",
            "demo",
            remove_all=True,
        )
        is None
    )


def test_add_path_rejects_unknown_path_type():
    with pytest.raises(JupyterHubValidationError, match="file, directory"):
        add_path(
            "https://hub.example/hub/api/",
            "token",
            "demo",
            destination="work",
            path_type="symlink",
        )


def test_exec_command_rejects_empty_command_before_network_access(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("Network helper must not run for invalid public input")

    monkeypatch.setattr(client_module, "_get_full_user_output", fail_if_called)

    with pytest.raises(JupyterHubValidationError, match="command"):
        exec_command(
            "https://hub.example/hub/api/",
            "token",
            "demo",
            command=(),
        )


def test_client_wrapper_stores_common_context(monkeypatch):
    calls = []

    def fake_get_servers(
        hub_api_endpoint,
        token,
        user=None,
        include_stopped_servers=False,
    ):
        calls.append(
            {
                "hub_api_endpoint": hub_api_endpoint,
                "token": token,
                "user": user,
                "include_stopped_servers": include_stopped_servers,
            }
        )
        return {}

    monkeypatch.setattr(client_module, "get_servers", fake_get_servers)

    client = JupyterHubClient("https://hub.example/hub/api/", "token", user="alice")

    assert client.get_servers(include_stopped_servers=True) == {}
    assert calls == [
        {
            "hub_api_endpoint": "https://hub.example/hub/api/",
            "token": "token",
            "user": "alice",
            "include_stopped_servers": True,
        }
    ]


PUBLIC_CLIENT_METHODS = (
    JupyterHubClient.get_user,
    JupyterHubClient.get_servers,
    JupyterHubClient.start_server,
    JupyterHubClient.stop_server,
    JupyterHubClient.add_shared_access,
    JupyterHubClient.remove_shared_access,
    JupyterHubClient.list_shared_access,
    JupyterHubClient.get_token,
    JupyterHubClient.add_token,
    JupyterHubClient.delete_token,
    JupyterHubClient.list_tokens,
    JupyterHubClient.get_path,
    JupyterHubClient.add_path,
    JupyterHubClient.delete_path,
    JupyterHubClient.upload_file,
    JupyterHubClient.exec_command,
)


def test_client_methods_are_explicit_and_do_not_repeat_connection_parameters():
    """The preferred object API stores endpoint and token on the client."""
    for method in PUBLIC_CLIENT_METHODS:
        signature = inspect.signature(method)
        parameters = signature.parameters

        assert "hub_api_endpoint" not in parameters, method.__name__
        assert "token" not in parameters, method.__name__
        assert not any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        ), method.__name__
        assert all(
            parameter.annotation is not inspect.Signature.empty
            for name, parameter in parameters.items()
            if name != "self"
        ), method.__name__
        assert (
            signature.return_annotation is not inspect.Signature.empty
        ), method.__name__
