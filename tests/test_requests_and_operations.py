"""Tests that successful public operations construct the expected API requests."""

import json

import pytest

import fedcloud_jupyterhub.client as client_module
from fedcloud_jupyterhub import JupyterHubResponseError


class DummyResponse:
    def __init__(self, payload=None):
        self.ok = True
        self.status_code = 200
        self.reason = "OK"
        self.text = ""
        self._payload = {} if payload is None else payload

    def json(self):
        return self._payload


def test_get_user_builds_expected_hub_api_request(monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return DummyResponse({"name": "alice", "servers": {}})

    monkeypatch.setattr(client_module.requests, "request", fake_request)

    result = client_module.get_user(
        "https://hub.example/hub/api",
        "secret",
        user="alice",
        include_stopped_servers=True,
    )

    assert result["name"] == "alice"
    method, url, kwargs = calls[0]
    assert method == "GET"
    assert url == "https://hub.example/hub/api/users/alice"
    assert kwargs["headers"] == {"Authorization": "Bearer secret"}
    assert kwargs["params"] == {"include_stopped_servers": True}


def test_get_servers_rejects_user_model_without_servers(monkeypatch):
    monkeypatch.setattr(client_module, "get_user", lambda **kwargs: {"name": "alice"})

    with pytest.raises(JupyterHubResponseError, match="servers"):
        client_module.get_servers("https://hub.example/hub/api/", "token")


def test_start_server_uses_resolved_user_and_json_body(monkeypatch):
    calls = []
    monkeypatch.setattr(client_module, "_get_user_id", lambda *args, **kwargs: "alice")
    monkeypatch.setattr(
        client_module,
        "_make_request",
        lambda **kwargs: calls.append(kwargs) or DummyResponse(),
    )

    client_module.start_server(
        "https://hub.example/hub/api/",
        "token",
        "gpu",
        options='{"profile": "gpu"}',
    )

    assert calls == [
        {
            "hub_api_endpoint": "https://hub.example/hub/api/",
            "token": "token",
            "method": "post",
            "api_request_endpoint": "users/alice/servers/gpu",
            "data": {"profile": "gpu"},
        }
    ]


def test_add_token_sends_roles_as_json_array(monkeypatch):
    calls = []
    monkeypatch.setattr(client_module, "_get_user_id", lambda *args, **kwargs: "alice")
    monkeypatch.setattr(
        client_module,
        "_make_request",
        lambda **kwargs: calls.append(kwargs)
        or DummyResponse({"id": "1", "token": "new-token"}),
    )

    result = client_module.add_token(
        "https://hub.example/hub/api/",
        "token",
        expiration=3600,
        note="automation",
        role=("user", "reader"),
    )

    assert result["id"] == "1"
    assert calls[0]["api_request_endpoint"] == "users/alice/tokens"
    assert calls[0]["data"] == {
        "expires_in": 3600,
        "note": "automation",
        "roles": ["user", "reader"],
    }


def test_add_shared_access_sends_expected_payload(monkeypatch):
    calls = []
    monkeypatch.setattr(client_module, "_get_user_id", lambda *args, **kwargs: "alice")
    monkeypatch.setattr(
        client_module,
        "_make_request",
        lambda **kwargs: calls.append(kwargs)
        or DummyResponse({"user": "bob", "scopes": ["access:servers"]}),
    )

    result = client_module.add_shared_access(
        "https://hub.example/hub/api/",
        "token",
        "demo",
        grant_to_user="bob",
        scope=("access:servers",),
    )

    assert result["user"] == "bob"
    assert calls[0]["api_request_endpoint"] == "shares/alice/demo"
    assert calls[0]["data"] == {
        "user": "bob",
        "scopes": ["access:servers"],
    }


def test_exec_command_uses_server_url_from_user_model(monkeypatch):
    calls = []
    monkeypatch.setattr(
        client_module,
        "_get_full_user_output",
        lambda *args, **kwargs: {
            "name": "alice",
            "servers": {"demo": {"url": "/user/alice/demo/"}},
        },
    )
    monkeypatch.setattr(
        client_module,
        "_make_request",
        lambda **kwargs: calls.append(kwargs)
        or DummyResponse({"output": "hello\n", "return_code": 0}),
    )

    output = client_module.exec_command(
        "https://hub.example/hub/api/",
        "token",
        "demo",
        ("echo", "hello"),
    )

    assert output == "hello\n"
    assert calls[0]["hub_api_endpoint"] == "https://hub.example/user/alice/demo/"
    assert calls[0]["api_request_endpoint"] == "jlab-control/exec"
    assert calls[0]["data"] == {"command": ["echo", "hello"]}


def test_make_request_serializes_json_and_does_not_mutate_payload(monkeypatch):
    calls = []
    payload = {"items": ("a", "b")}

    def fake_request(method, url, **kwargs):
        calls.append(kwargs)
        return DummyResponse({})

    monkeypatch.setattr(client_module.requests, "request", fake_request)

    client_module._make_request(
        hub_api_endpoint="https://hub.example/hub/api/",
        token="token",
        method="post",
        api_request_endpoint="example",
        data=payload,
    )

    assert payload == {"items": ("a", "b")}
    assert json.loads(calls[0]["data"]) == {"items": ["a", "b"]}


def test_get_path_targets_running_server_contents_api(monkeypatch):
    calls = []
    monkeypatch.setattr(
        client_module,
        "_get_full_user_output",
        lambda *args, **kwargs: {
            "name": "alice",
            "servers": {"demo": {"url": "/user/alice/demo/"}},
        },
    )
    monkeypatch.setattr(
        client_module,
        "_make_request",
        lambda **kwargs: calls.append(kwargs)
        or DummyResponse({"path": "work", "type": "directory"}),
    )

    result = client_module.get_path(
        "https://hub.example/hub/api/",
        "token",
        "demo",
        "/work",
        show_content=True,
    )

    assert result["type"] == "directory"
    assert calls[0]["hub_api_endpoint"] == "https://hub.example/user/alice/demo/api/"
    assert calls[0]["api_request_endpoint"] == "contents/work"
    assert calls[0]["params"] == {"content": 1}


def test_add_path_renames_created_item_when_name_is_requested(monkeypatch):
    calls = []
    responses = iter(
        [
            {"path": "work/Untitled Folder", "type": "directory"},
            {"path": "work/results", "type": "directory"},
        ]
    )

    def fake_path_request(**kwargs):
        calls.append(kwargs)
        return next(responses)

    monkeypatch.setattr(client_module, "_path_request", fake_path_request)

    result = client_module.add_path(
        "https://hub.example/hub/api/",
        "token",
        "demo",
        destination="work",
        path_type="directory",
        name="results",
    )

    assert result["path"] == "work/results"
    assert calls[0]["method"] == "post"
    assert calls[0]["data"] == {"type": "directory"}
    assert calls[1]["method"] == "patch"
    assert calls[1]["destination"] == "work/Untitled Folder"
    assert calls[1]["data"] == {"path": "work/results"}


def test_upload_file_encodes_local_content_and_uses_file_destination(
    monkeypatch, tmp_path
):
    source = tmp_path / "hello.txt"
    source.write_bytes(b"hello")
    calls = []

    monkeypatch.setattr(
        client_module,
        "get_path",
        lambda **kwargs: {"path": "remote.txt", "type": "file"},
    )
    monkeypatch.setattr(
        client_module,
        "_path_request",
        lambda **kwargs: calls.append(kwargs) or {"path": "remote.txt", "type": "file"},
    )

    result = client_module.upload_file(
        "https://hub.example/hub/api/",
        "token",
        "demo",
        str(source),
        "remote.txt",
    )

    assert result["path"] == "remote.txt"
    assert calls[0]["method"] == "put"
    assert calls[0]["data"]["content"] == "aGVsbG8="
    assert calls[0]["data"]["path"] == "remote.txt"


def test_get_server_url_reports_missing_server_as_not_found():
    with pytest.raises(client_module.JupyterHubNotFoundError, match="does not exist"):
        client_module._get_server_url(
            "https://hub.example/hub/api/",
            "missing",
            {"servers": {}},
        )


def test_exec_command_reports_missing_server_extension(monkeypatch):
    monkeypatch.setattr(
        client_module,
        "_get_full_user_output",
        lambda *args, **kwargs: {
            "name": "alice",
            "servers": {"demo": {"url": "/user/alice/demo/"}},
        },
    )

    def missing_extension(**kwargs):
        raise client_module.JupyterHubNotFoundError(
            404,
            "Not Found",
            reason="Not Found",
            url="https://hub.example/user/alice/demo/jlab-control/exec",
        )

    monkeypatch.setattr(client_module, "_make_request", missing_extension)

    with pytest.raises(
        client_module.JupyterHubNotFoundError,
        match="jupyterlab_control_exec",
    ):
        client_module.exec_command(
            "https://hub.example/hub/api/",
            "token",
            "demo",
            ("echo", "hello"),
        )
