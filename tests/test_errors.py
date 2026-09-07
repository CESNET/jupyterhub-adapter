"""Tests for structured exceptions and logging-safe request handling."""

import pytest
import requests

import fedcloud_jupyterhub.client as client_module
from fedcloud_jupyterhub import (
    JupyterHubAPIError,
    JupyterHubAuthenticationError,
    JupyterHubFileError,
    JupyterHubNotFoundError,
    JupyterHubRequestError,
    JupyterHubResponseError,
)


class DummyResponse:
    def __init__(
        self,
        *,
        ok=True,
        status_code=200,
        payload=None,
        reason="OK",
        text="",
        json_error=None,
    ):
        self.ok = ok
        self.status_code = status_code
        self._payload = payload
        self.reason = reason
        self.text = text
        self._json_error = json_error

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._payload


def test_http_404_is_a_not_found_exception(monkeypatch):
    response = DummyResponse(
        ok=False,
        status_code=404,
        payload={"message": "No such user"},
        reason="Not Found",
    )
    monkeypatch.setattr(requests, "request", lambda *args, **kwargs: response)

    with pytest.raises(JupyterHubNotFoundError) as error:
        client_module._make_request(
            hub_api_endpoint="https://hub.example/hub/api/",
            token="secret",
            method="get",
            api_request_endpoint="users/missing",
        )

    assert error.value.status_code == 404
    assert error.value.message == "No such user"
    assert "secret" not in str(error.value)


def test_http_403_is_an_authentication_exception(monkeypatch):
    response = DummyResponse(
        ok=False,
        status_code=403,
        payload={"message": "Forbidden"},
        reason="Forbidden",
    )
    monkeypatch.setattr(requests, "request", lambda *args, **kwargs: response)

    with pytest.raises(JupyterHubAuthenticationError):
        client_module._make_request(
            hub_api_endpoint="https://hub.example/hub/api/",
            token="secret",
            method="get",
            api_request_endpoint="user",
        )


def test_generic_http_error_preserves_status_and_fallback_reason(monkeypatch):
    response = DummyResponse(
        ok=False,
        status_code=500,
        reason="Internal Server Error",
        json_error=ValueError("not json"),
    )
    monkeypatch.setattr(requests, "request", lambda *args, **kwargs: response)

    with pytest.raises(JupyterHubAPIError) as error:
        client_module._make_request(
            hub_api_endpoint="https://hub.example/hub/api/",
            token="secret",
            method="get",
            api_request_endpoint="user",
        )

    assert error.value.status_code == 500
    assert error.value.message == "Internal Server Error"


def test_transport_failure_is_wrapped(monkeypatch):
    def fail(*args, **kwargs):
        raise requests.ConnectionError("connection refused")

    monkeypatch.setattr(requests, "request", fail)

    with pytest.raises(JupyterHubRequestError, match="connection refused"):
        client_module._make_request(
            hub_api_endpoint="https://hub.example/hub/api/",
            token="secret",
            method="get",
            api_request_endpoint="user",
        )


def test_successful_non_json_response_raises_response_error():
    response = DummyResponse(json_error=ValueError("invalid json"))

    with pytest.raises(JupyterHubResponseError, match="decode JSON"):
        client_module._decode_response(response)


def test_successful_json_array_raises_response_error():
    response = DummyResponse(payload=[1, 2, 3])

    with pytest.raises(JupyterHubResponseError, match="JSON object"):
        client_module._decode_response(response)


def test_upload_file_raises_file_error_for_unreadable_local_file(monkeypatch):
    monkeypatch.setattr(
        client_module,
        "get_path",
        lambda **kwargs: {"type": "directory", "path": "destination"},
    )

    with pytest.raises(JupyterHubFileError, match="Failed to read local file"):
        client_module.upload_file(
            "https://hub.example/hub/api/",
            "token",
            "demo",
            "/definitely/not/a/real/file",
            "destination",
        )


def test_library_error_paths_do_not_print_to_stdout(monkeypatch, capsys):
    response = DummyResponse(
        ok=False,
        status_code=500,
        payload={"message": "boom"},
        reason="Internal Server Error",
    )
    monkeypatch.setattr(requests, "request", lambda *args, **kwargs: response)

    with pytest.raises(JupyterHubAPIError):
        client_module._make_request(
            hub_api_endpoint="https://hub.example/hub/api/",
            token="secret",
            method="get",
            api_request_endpoint="user",
        )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_application_level_error_in_successful_json_is_raised():
    response = DummyResponse(payload={"status": 403, "message": "Forbidden"})

    with pytest.raises(JupyterHubAuthenticationError) as error:
        client_module._decode_response(response)

    assert error.value.status_code == 403
    assert error.value.message == "Forbidden"
