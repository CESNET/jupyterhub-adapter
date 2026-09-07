"""Standalone Python API for JupyterHub adapter operations.

The functions in this module form the public library API.  They use explicit
parameters, validate caller input at the public boundary, raise typed
exceptions on failures, and never print to stdout.  The optional Click CLI in
``fedcloud_jupyterhub.cli`` is intentionally implemented as a presentation
layer on top of these functions.
"""

import base64
import json
import logging
import os
import urllib.parse
from typing import Any, Dict, Mapping, Optional, Sequence, Union

import requests

from fedcloud_jupyterhub.exceptions import (
    JupyterHubAPIError,
    JupyterHubAuthenticationError,
    JupyterHubFileError,
    JupyterHubNotFoundError,
    JupyterHubRequestError,
    JupyterHubResponseError,
    JupyterHubValidationError,
)

logger = logging.getLogger(__name__)

JsonObject = Dict[str, Any]
StringSequence = Sequence[str]
ServerOptions = Optional[Union[str, Mapping[str, Any]]]


def _validate_required(values: Mapping[str, Any], *names: str) -> None:
    """Raise a validation error when any required argument is ``None``."""
    missing = [name for name in names if values.get(name) is None]
    if missing:
        raise JupyterHubValidationError(
            "Missing required argument(s): " + ", ".join(missing)
        )


def _validate_non_empty(values: Mapping[str, Any], *names: str) -> None:
    """Raise a validation error when a required string/sequence is empty."""
    empty = [name for name in names if values.get(name) in ("", (), [], {})]
    if empty:
        raise JupyterHubValidationError(
            "Argument(s) must not be empty: " + ", ".join(empty)
        )


def _validate_common(values: Mapping[str, Any]) -> None:
    """Validate parameters required by every Hub API operation."""
    _validate_required(values, "hub_api_endpoint", "token")
    _validate_non_empty(values, "hub_api_endpoint", "token")


def _validate_server(values: Mapping[str, Any]) -> None:
    """Validate parameters required by server-specific operations.

    An empty server name is valid in JupyterHub and identifies the default,
    unnamed server, therefore this helper checks only for ``None``.
    """
    _validate_common(values)
    _validate_required(values, "server")


def _validate_exclusive(values: Mapping[str, Any], left: str, right: str) -> None:
    """Validate that two optional arguments are not supplied together."""
    left_value = values.get(left)
    right_value = values.get(right)
    if left_value not in (None, (), "") and right_value not in (None, (), ""):
        raise JupyterHubValidationError(
            f"Arguments '{left}' and '{right}' cannot be specified at the same time"
        )


def _validate_exactly_one(values: Mapping[str, Any], left: str, right: str) -> None:
    """Validate that exactly one of two optional arguments is supplied."""
    _validate_exclusive(values, left, right)
    left_value = values.get(left)
    right_value = values.get(right)
    if left_value in (None, (), "") and right_value in (None, (), ""):
        raise JupyterHubValidationError(
            f"Exactly one of '{left}' or '{right}' must be specified"
        )


def _validate_choice(
    values: Mapping[str, Any], name: str, allowed: Sequence[str]
) -> None:
    """Validate that an optional argument uses one of the allowed values."""
    if values.get(name) is not None and values[name] not in allowed:
        raise JupyterHubValidationError(
            f"Argument '{name}' must be one of: {', '.join(allowed)}"
        )


def _decode_error_message(response: requests.Response) -> str:
    """Return the most useful human-readable message from an error response."""
    try:
        payload = response.json()
    except ValueError:
        payload = None

    if isinstance(payload, Mapping):
        for key in ("message", "error", "detail"):
            value = payload.get(key)
            if value:
                return str(value)

    reason = getattr(response, "reason", None)
    if reason:
        return str(reason)

    text = getattr(response, "text", "")
    if text:
        return text.strip()

    return "Remote service returned an error response"


def _raise_api_error(response: requests.Response, url: str) -> None:
    """Translate an unsuccessful HTTP response into a typed exception."""
    status_code = response.status_code
    message = _decode_error_message(response)
    reason = getattr(response, "reason", None)

    exception_type = JupyterHubAPIError
    if status_code in (401, 403):
        exception_type = JupyterHubAuthenticationError
    elif status_code == 404:
        exception_type = JupyterHubNotFoundError

    raise exception_type(
        status_code,
        message,
        reason=reason,
        url=url,
    )


def _make_request(
    *,
    hub_api_endpoint: str,
    token: str,
    method: str,
    api_request_endpoint: str,
    data: Optional[Mapping[str, Any]] = None,
    params: Optional[Mapping[str, Any]] = None,
) -> requests.Response:
    """Send one authenticated request to a Hub or single-user-server endpoint."""
    base_endpoint = hub_api_endpoint
    if not base_endpoint.endswith("/"):
        base_endpoint += "/"

    url = urllib.parse.urljoin(base_endpoint, api_request_endpoint)
    headers = {"Authorization": f"Bearer {token}"}
    request_data = None

    if data is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
        request_data = json.dumps(data)

    logger.debug("Sending JupyterHub adapter request: %s %s", method.upper(), url)

    try:
        response = requests.request(
            method.upper(),
            url,
            headers=headers,
            params=params,
            data=request_data,
        )
    except requests.RequestException as exc:
        logger.warning(
            "JupyterHub adapter request failed before a response was received"
        )
        raise JupyterHubRequestError(
            f"Failed to complete {method.upper()} request to {url}: {exc}"
        ) from exc

    if not response.ok:
        logger.info(
            "JupyterHub adapter request returned HTTP %s for %s %s",
            response.status_code,
            method.upper(),
            url,
        )
        _raise_api_error(response, url)

    return response


def _decode_response(response: requests.Response) -> JsonObject:
    """Decode a successful JSON response and validate its top-level type."""
    try:
        payload = response.json()
    except ValueError as exc:
        raise JupyterHubResponseError(
            "Failed to decode JSON from a successful JupyterHub response"
        ) from exc

    if not isinstance(payload, dict):
        raise JupyterHubResponseError(
            "Expected a JSON object in the JupyterHub response"
        )

    # Some adapter-facing services encode an error inside a JSON response even
    # when the transport-level HTTP status is successful.  Treat such payloads
    # exactly like normal Hub HTTP errors so callers do not have to special-case
    # two different error conventions.
    embedded_status = payload.get("status")
    if isinstance(embedded_status, int) and embedded_status >= 400:
        message = payload.get("message") or payload.get("reason")
        if message is None:
            message = "Remote service reported an application-level error"
        exception_type = JupyterHubAPIError
        if embedded_status in (401, 403):
            exception_type = JupyterHubAuthenticationError
        elif embedded_status == 404:
            exception_type = JupyterHubNotFoundError
        raise exception_type(embedded_status, str(message))

    return payload


def _get_user_id(
    hub_api_endpoint: str,
    token: str,
    user: Optional[str] = None,
    include_stopped_servers: bool = False,
) -> str:
    """Return the resolved Hub user name used by user-specific API endpoints."""
    user_output = get_user(
        hub_api_endpoint=hub_api_endpoint,
        token=token,
        user=user,
        include_stopped_servers=include_stopped_servers,
    )

    user_id = user_output.get("name")
    if not isinstance(user_id, str) or not user_id:
        raise JupyterHubResponseError(
            "JupyterHub user response does not contain a valid 'name' field"
        )
    return user_id


def _get_full_user_output(
    hub_api_endpoint: str,
    token: str,
    user: Optional[str] = None,
) -> JsonObject:
    """Return user details including stopped servers for server URL resolution."""
    return get_user(
        hub_api_endpoint=hub_api_endpoint,
        token=token,
        user=user,
        include_stopped_servers=True,
    )


def _get_server_url(
    hub_api_endpoint: str,
    server_name: str,
    user_output: Mapping[str, Any],
) -> str:
    """Resolve the externally reachable URL of a server from a user model."""
    servers = user_output.get("servers")
    if not isinstance(servers, Mapping):
        raise JupyterHubResponseError(
            "JupyterHub user response does not contain a valid 'servers' mapping"
        )

    if server_name not in servers:
        raise JupyterHubNotFoundError(
            404,
            f"Server '{server_name}' does not exist in the JupyterHub user model",
        )

    server_model = servers[server_name]
    if not isinstance(server_model, Mapping):
        raise JupyterHubResponseError(
            f"JupyterHub server model for '{server_name}' has an invalid structure"
        )

    server_url_path = server_model.get("url")
    if not isinstance(server_url_path, str) or not server_url_path:
        raise JupyterHubResponseError(
            f"JupyterHub server model for '{server_name}' does not contain a valid URL"
        )

    if not server_url_path.endswith("/"):
        server_url_path += "/"
    if server_url_path.startswith("/"):
        server_url_path = server_url_path[1:]

    hub_address = urllib.parse.urlsplit(hub_api_endpoint)
    hub_origin = urllib.parse.urlunsplit(
        (hub_address.scheme, hub_address.netloc, "", "", "")
    )
    return urllib.parse.urljoin(hub_origin + "/", server_url_path)


def get_user(
    hub_api_endpoint: str,
    token: str,
    user: Optional[str] = None,
    include_stopped_servers: bool = False,
) -> JsonObject:
    """Return details for a JupyterHub user or the owner of the API token.

    Args:
        hub_api_endpoint: Base JupyterHub REST API URL, usually ending in
            ``/hub/api/``.
        token: JupyterHub API token used for authentication.
        user: Optional user name. If omitted, the token owner's model is
            requested from the ``user`` endpoint.
        include_stopped_servers: Request stopped named servers in the returned
            user model as well as running servers.

    Returns:
        The JupyterHub user model as a dictionary.

    Raises:
        JupyterHubValidationError: If required arguments are missing or empty.
        JupyterHubRequestError: If the HTTP request cannot be completed.
        JupyterHubAPIError: If JupyterHub returns an unsuccessful HTTP status.
        JupyterHubResponseError: If the successful response is not valid JSON.
    """
    values = {"hub_api_endpoint": hub_api_endpoint, "token": token}
    _validate_common(values)

    api_request_endpoint = f"users/{user}" if user is not None else "user"
    response = _make_request(
        hub_api_endpoint=hub_api_endpoint,
        token=token,
        method="get",
        api_request_endpoint=api_request_endpoint,
        params={"include_stopped_servers": include_stopped_servers},
    )
    return _decode_response(response)


def get_servers(
    hub_api_endpoint: str,
    token: str,
    user: Optional[str] = None,
    include_stopped_servers: bool = False,
) -> JsonObject:
    """Return the named-server mapping for a JupyterHub user.

    Args:
        hub_api_endpoint: Base JupyterHub REST API URL.
        token: JupyterHub API token used for authentication.
        user: Optional user name. If omitted, the token owner is used.
        include_stopped_servers: Include stopped servers in the Hub user model.

    Returns:
        Mapping of server names to JupyterHub server models.

    Raises:
        JupyterHubResponseError: If the user model does not contain a valid
            ``servers`` mapping.
        JupyterHubError: Any error raised while acquiring the user model.
    """
    user_output = get_user(
        hub_api_endpoint=hub_api_endpoint,
        token=token,
        user=user,
        include_stopped_servers=include_stopped_servers,
    )
    servers = user_output.get("servers")
    if not isinstance(servers, dict):
        raise JupyterHubResponseError(
            "JupyterHub user response does not contain a valid 'servers' mapping"
        )
    return servers


def _parse_server_options(options: ServerOptions) -> Optional[Mapping[str, Any]]:
    """Normalize server spawn options accepted by the Python API and CLI."""
    if options is None:
        return None
    if isinstance(options, Mapping):
        return dict(options)
    if isinstance(options, str):
        try:
            decoded = json.loads(options)
        except json.JSONDecodeError as exc:
            raise JupyterHubValidationError(
                "Argument 'options' must be valid JSON"
            ) from exc
        if not isinstance(decoded, dict):
            raise JupyterHubValidationError(
                "Argument 'options' must decode to a JSON object"
            )
        return decoded
    raise JupyterHubValidationError(
        "Argument 'options' must be a mapping, a JSON object string, or None"
    )


def _server_start_stop(
    *,
    hub_api_endpoint: str,
    token: str,
    server: str,
    user: Optional[str],
    method: str,
    options: ServerOptions = None,
) -> None:
    """Start or stop one JupyterHub single-user server."""
    user_id = _get_user_id(hub_api_endpoint, token, user)
    request_data = _parse_server_options(options)

    _make_request(
        hub_api_endpoint=hub_api_endpoint,
        token=token,
        method=method,
        api_request_endpoint=f"users/{user_id}/servers/{server}",
        data=request_data,
    )


def start_server(
    hub_api_endpoint: str,
    token: str,
    server: str,
    user: Optional[str] = None,
    options: ServerOptions = None,
) -> None:
    """Start a JupyterHub server.

    Args:
        hub_api_endpoint: Base JupyterHub REST API URL.
        token: JupyterHub API token used for authentication.
        server: Named-server name. Use an empty string for the default server.
        user: Optional owner of the server. If omitted, the token owner is used.
        options: Optional spawner options as a mapping or JSON object string.

    Raises:
        JupyterHubValidationError: If parameters or JSON options are invalid.
        JupyterHubError: If resolving the user or starting the server fails.
    """
    values = {
        "hub_api_endpoint": hub_api_endpoint,
        "token": token,
        "server": server,
    }
    _validate_server(values)
    # Parse here as well as in the helper so invalid caller input is rejected at
    # the public function boundary before any network request is attempted.
    _parse_server_options(options)
    _server_start_stop(
        hub_api_endpoint=hub_api_endpoint,
        token=token,
        server=server,
        user=user,
        options=options,
        method="post",
    )


def stop_server(
    hub_api_endpoint: str,
    token: str,
    server: str,
    user: Optional[str] = None,
) -> None:
    """Stop a JupyterHub server.

    Args:
        hub_api_endpoint: Base JupyterHub REST API URL.
        token: JupyterHub API token used for authentication.
        server: Named-server name. Use an empty string for the default server.
        user: Optional owner of the server. If omitted, the token owner is used.

    Raises:
        JupyterHubValidationError: If required parameters are invalid.
        JupyterHubError: If resolving the user or stopping the server fails.
    """
    values = {
        "hub_api_endpoint": hub_api_endpoint,
        "token": token,
        "server": server,
    }
    _validate_server(values)
    _server_start_stop(
        hub_api_endpoint=hub_api_endpoint,
        token=token,
        server=server,
        user=user,
        method="delete",
    )


def _shares_request(
    *,
    hub_api_endpoint: str,
    token: str,
    server: str,
    user: Optional[str],
    method: str,
    grant_to_user: Optional[str] = None,
    grant_to_group: Optional[str] = None,
    remove_from_user: Optional[str] = None,
    remove_from_group: Optional[str] = None,
    scope: StringSequence = (),
) -> Optional[JsonObject]:
    """Send a request to the JupyterHub shares API."""
    data: Optional[JsonObject] = None
    if method in ("post", "patch"):
        data = {}
        data_items = (
            (grant_to_group, "group"),
            (grant_to_user, "user"),
            (remove_from_user, "user"),
            (remove_from_group, "group"),
        )
        for value, api_key in data_items:
            if value is not None:
                data[api_key] = value
        # Preserve the original adapter semantics: an explicitly empty scope
        # collection is sent as an empty JSON list rather than omitted.  This
        # lets JupyterHub apply the same default-share behavior as before the
        # library extraction.
        data["scopes"] = list(scope)

    user_id = user if user is not None else _get_user_id(hub_api_endpoint, token)
    response = _make_request(
        hub_api_endpoint=hub_api_endpoint,
        token=token,
        method=method,
        api_request_endpoint=f"shares/{user_id}/{server}",
        data=data,
    )
    if method == "delete":
        return None
    return _decode_response(response)


def add_shared_access(
    hub_api_endpoint: str,
    token: str,
    server: str,
    user: Optional[str] = None,
    grant_to_user: Optional[str] = None,
    grant_to_group: Optional[str] = None,
    scope: StringSequence = (),
) -> JsonObject:
    """Grant shared access to a JupyterHub user server.

    Exactly one of ``grant_to_user`` and ``grant_to_group`` must be supplied.

    Args:
        hub_api_endpoint: Base JupyterHub REST API URL.
        token: JupyterHub API token used for authentication.
        server: Server whose access is being shared.
        user: Optional owner of the server. If omitted, the token owner is used.
        grant_to_user: User name receiving access.
        grant_to_group: Group name receiving access.
        scope: Optional sequence of JupyterHub scopes to grant.

    Returns:
        The share model returned by JupyterHub.

    Raises:
        JupyterHubValidationError: If both or neither share recipients are set.
        JupyterHubError: If the Hub request or response processing fails.
    """
    values = {
        "hub_api_endpoint": hub_api_endpoint,
        "token": token,
        "server": server,
        "grant_to_user": grant_to_user,
        "grant_to_group": grant_to_group,
    }
    _validate_server(values)
    _validate_exactly_one(values, "grant_to_user", "grant_to_group")
    result = _shares_request(
        hub_api_endpoint=hub_api_endpoint,
        token=token,
        server=server,
        user=user,
        grant_to_user=grant_to_user,
        grant_to_group=grant_to_group,
        scope=scope,
        method="post",
    )
    if result is None:  # pragma: no cover - POST always returns decoded output
        raise JupyterHubResponseError("JupyterHub did not return a share model")
    return result


def remove_shared_access(
    hub_api_endpoint: str,
    token: str,
    server: str,
    user: Optional[str] = None,
    remove_from_user: Optional[str] = None,
    remove_from_group: Optional[str] = None,
    scope: StringSequence = (),
    remove_all: bool = False,
) -> Optional[JsonObject]:
    """Remove shared access from a JupyterHub user server.

    Args:
        hub_api_endpoint: Base JupyterHub REST API URL.
        token: JupyterHub API token used for authentication.
        server: Server whose share is being modified.
        user: Optional owner of the server. If omitted, the token owner is used.
        remove_from_user: User from whom access is removed.
        remove_from_group: Group from which access is removed.
        scope: Optional scopes to remove when ``remove_all`` is false.
        remove_all: Remove all sharing entries from the server using DELETE.

    Returns:
        Updated share information for a scoped removal, or ``None`` after a
        successful remove-all DELETE request.

    Raises:
        JupyterHubValidationError: If recipient arguments are inconsistent.
        JupyterHubError: If the Hub request or response processing fails.
    """
    values = {
        "hub_api_endpoint": hub_api_endpoint,
        "token": token,
        "server": server,
        "remove_from_user": remove_from_user,
        "remove_from_group": remove_from_group,
    }
    _validate_server(values)
    if remove_all:
        _validate_exclusive(values, "remove_from_user", "remove_from_group")
    else:
        _validate_exactly_one(values, "remove_from_user", "remove_from_group")

    return _shares_request(
        hub_api_endpoint=hub_api_endpoint,
        token=token,
        server=server,
        user=user,
        remove_from_user=remove_from_user,
        remove_from_group=remove_from_group,
        scope=scope,
        method="delete" if remove_all else "patch",
    )


def list_shared_access(
    hub_api_endpoint: str,
    token: str,
    server: str,
    user: Optional[str] = None,
) -> JsonObject:
    """List sharing information for a JupyterHub user server.

    Args:
        hub_api_endpoint: Base JupyterHub REST API URL.
        token: JupyterHub API token used for authentication.
        server: Server whose sharing information is requested.
        user: Optional owner of the server. If omitted, the token owner is used.

    Returns:
        Sharing information returned by JupyterHub.
    """
    values = {
        "hub_api_endpoint": hub_api_endpoint,
        "token": token,
        "server": server,
    }
    _validate_server(values)
    result = _shares_request(
        hub_api_endpoint=hub_api_endpoint,
        token=token,
        server=server,
        user=user,
        method="get",
    )
    if result is None:  # pragma: no cover - GET always returns decoded output
        raise JupyterHubResponseError("JupyterHub did not return sharing information")
    return result


def _token_request(
    *,
    hub_api_endpoint: str,
    token: str,
    user: Optional[str],
    method: str,
    api_token_id: Optional[str] = None,
    expiration: Optional[int] = None,
    note: Optional[str] = None,
    role: StringSequence = (),
    scope: StringSequence = (),
) -> Optional[JsonObject]:
    """Send a request to the JupyterHub user-token API."""
    data: Optional[JsonObject] = None
    if method == "post":
        data = {}
        if expiration is not None:
            data["expires_in"] = expiration
        if note is not None:
            data["note"] = note
        if role:
            data["roles"] = list(role)
        if scope:
            data["scopes"] = list(scope)

    user_id = user if user is not None else _get_user_id(hub_api_endpoint, token)
    endpoint = f"users/{user_id}/tokens"
    if api_token_id is not None:
        endpoint += f"/{api_token_id}"

    response = _make_request(
        hub_api_endpoint=hub_api_endpoint,
        token=token,
        method=method,
        api_request_endpoint=endpoint,
        data=data,
    )
    if method == "delete":
        return None
    return _decode_response(response)


def get_token(
    hub_api_endpoint: str,
    token: str,
    api_token_id: str,
    user: Optional[str] = None,
) -> JsonObject:
    """Return details of one JupyterHub API token.

    Args:
        hub_api_endpoint: Base JupyterHub REST API URL.
        token: JupyterHub API token used for authentication.
        api_token_id: Identifier of the API token to retrieve.
        user: Optional owner of the API token. If omitted, token owner is used.

    Returns:
        JupyterHub API token model.
    """
    values = {
        "hub_api_endpoint": hub_api_endpoint,
        "token": token,
        "api_token_id": api_token_id,
    }
    _validate_common(values)
    _validate_required(values, "api_token_id")
    _validate_non_empty(values, "api_token_id")
    result = _token_request(
        hub_api_endpoint=hub_api_endpoint,
        token=token,
        api_token_id=api_token_id,
        user=user,
        method="get",
    )
    if result is None:  # pragma: no cover - GET always returns decoded output
        raise JupyterHubResponseError("JupyterHub did not return an API token model")
    return result


def delete_token(
    hub_api_endpoint: str,
    token: str,
    api_token_id: str,
    user: Optional[str] = None,
) -> None:
    """Delete one JupyterHub API token.

    Args:
        hub_api_endpoint: Base JupyterHub REST API URL.
        token: JupyterHub API token used for authentication.
        api_token_id: Identifier of the API token to delete.
        user: Optional owner of the API token. If omitted, token owner is used.
    """
    values = {
        "hub_api_endpoint": hub_api_endpoint,
        "token": token,
        "api_token_id": api_token_id,
    }
    _validate_common(values)
    _validate_required(values, "api_token_id")
    _validate_non_empty(values, "api_token_id")
    _token_request(
        hub_api_endpoint=hub_api_endpoint,
        token=token,
        api_token_id=api_token_id,
        user=user,
        method="delete",
    )


def list_tokens(
    hub_api_endpoint: str,
    token: str,
    user: Optional[str] = None,
) -> JsonObject:
    """List API tokens for a JupyterHub user.

    Args:
        hub_api_endpoint: Base JupyterHub REST API URL.
        token: JupyterHub API token used for authentication.
        user: Optional token owner. If omitted, the caller's Hub user is used.

    Returns:
        JupyterHub token-list response.
    """
    values = {"hub_api_endpoint": hub_api_endpoint, "token": token}
    _validate_common(values)
    result = _token_request(
        hub_api_endpoint=hub_api_endpoint,
        token=token,
        user=user,
        method="get",
    )
    if result is None:  # pragma: no cover - GET always returns decoded output
        raise JupyterHubResponseError("JupyterHub did not return API token information")
    return result


def add_token(
    hub_api_endpoint: str,
    token: str,
    user: Optional[str] = None,
    expiration: Optional[int] = None,
    note: Optional[str] = None,
    role: StringSequence = (),
    scope: StringSequence = (),
) -> JsonObject:
    """Create a JupyterHub API token for a user.

    ``role`` and ``scope`` are mutually exclusive because JupyterHub accepts
    either roles or explicit scopes when creating a token, not both.

    Args:
        hub_api_endpoint: Base JupyterHub REST API URL.
        token: JupyterHub API token used for authentication.
        user: Optional token owner. If omitted, the caller's Hub user is used.
        expiration: Lifetime of the new token in seconds. ``None`` leaves the
            Hub default unchanged; ``0`` requests a non-expiring token.
        note: Optional human-readable token description.
        role: Optional sequence of JupyterHub role names.
        scope: Optional sequence of explicit JupyterHub scopes.

    Returns:
        Newly created JupyterHub token model.
    """
    values = {
        "hub_api_endpoint": hub_api_endpoint,
        "token": token,
        "role": role,
        "scope": scope,
    }
    _validate_common(values)
    _validate_exclusive(values, "role", "scope")
    if expiration is not None and expiration < 0:
        raise JupyterHubValidationError("Argument 'expiration' must be >= 0")

    result = _token_request(
        hub_api_endpoint=hub_api_endpoint,
        token=token,
        user=user,
        expiration=expiration,
        note=note,
        role=role,
        scope=scope,
        method="post",
    )
    if result is None:  # pragma: no cover - POST always returns decoded output
        raise JupyterHubResponseError("JupyterHub did not return the created token")
    return result


def _path_request(
    *,
    hub_api_endpoint: str,
    token: str,
    server: str,
    user: Optional[str],
    method: str,
    path: Optional[str] = None,
    destination: Optional[str] = None,
    data: Optional[Mapping[str, Any]] = None,
    params: Optional[Mapping[str, Any]] = None,
) -> Optional[JsonObject]:
    """Send a request to the Jupyter Contents API of a running server."""
    user_output = _get_full_user_output(hub_api_endpoint, token, user)
    server_url = _get_server_url(hub_api_endpoint, server, user_output)
    contents_api = urllib.parse.urljoin(server_url, "api/")

    if method == "put":
        if data is None or not isinstance(data.get("path"), str):
            raise JupyterHubResponseError(
                "Internal upload request is missing the destination path"
            )
        content_path = str(data["path"])
    elif path is not None:
        content_path = path
    elif destination is not None:
        content_path = destination
    else:
        raise JupyterHubValidationError("A path or destination must be specified")

    content_path = content_path.lstrip("/")

    response = _make_request(
        hub_api_endpoint=contents_api,
        token=token,
        method=method,
        api_request_endpoint=f"contents/{content_path}",
        data=data,
        params=params,
    )

    if method == "delete":
        return None

    return _decode_response(response)


def get_path(
    hub_api_endpoint: str,
    token: str,
    server: str,
    path: str,
    user: Optional[str] = None,
    show_content: bool = False,
) -> JsonObject:
    """Return a file or directory model from a running Jupyter server.

    Args:
        hub_api_endpoint: Base JupyterHub REST API URL.
        token: JupyterHub API token used for authentication.
        server: Server hosting the requested path.
        path: Path relative to the Jupyter server's Contents API root.
        user: Optional server owner. If omitted, the token owner is used.
        show_content: Ask Jupyter to include file/directory contents in response.

    Returns:
        Jupyter Contents API model for the requested path.
    """
    values = {
        "hub_api_endpoint": hub_api_endpoint,
        "token": token,
        "server": server,
        "path": path,
    }
    _validate_server(values)
    _validate_required(values, "path")
    result = _path_request(
        hub_api_endpoint=hub_api_endpoint,
        token=token,
        server=server,
        path=path,
        user=user,
        method="get",
        params={"content": 1 if show_content else 0},
    )
    if result is None:  # pragma: no cover - GET returns decoded output
        raise JupyterHubResponseError("Jupyter did not return the requested path model")
    return result


def add_path(
    hub_api_endpoint: str,
    token: str,
    server: str,
    destination: str,
    path_type: str,
    user: Optional[str] = None,
    name: Optional[str] = None,
    copy_from: Optional[str] = None,
) -> JsonObject:
    """Create a file or directory on a running Jupyter server.

    Args:
        hub_api_endpoint: Base JupyterHub REST API URL.
        token: JupyterHub API token used for authentication.
        server: Server on which the path is created.
        destination: Parent path used for the create request.
        path_type: Either ``"file"`` or ``"directory"``.
        user: Optional server owner. If omitted, the token owner is used.
        name: Optional final name. When supplied, the item created by Jupyter is
            renamed with a follow-up PATCH request.
        copy_from: Optional server-side source path copied by Jupyter.

    Returns:
        Jupyter Contents API model of the created (and possibly renamed) item.
    """
    values = {
        "hub_api_endpoint": hub_api_endpoint,
        "token": token,
        "server": server,
        "destination": destination,
        "path_type": path_type,
    }
    _validate_server(values)
    _validate_required(values, "destination", "path_type")
    _validate_choice(values, "path_type", ("file", "directory"))

    data: JsonObject = {"type": path_type}
    if copy_from is not None:
        data["copy_from"] = copy_from

    add_path_response = _path_request(
        hub_api_endpoint=hub_api_endpoint,
        token=token,
        server=server,
        destination=destination,
        user=user,
        method="post",
        data=data,
    )
    if add_path_response is None:  # pragma: no cover - POST returns decoded output
        raise JupyterHubResponseError("Jupyter did not return the created path model")

    if name is not None:
        created_path = add_path_response.get("path")
        if not isinstance(created_path, str):
            raise JupyterHubResponseError(
                "Jupyter create-path response does not contain a valid 'path' field"
            )
        new_path = os.path.join(os.path.dirname(created_path), name)
        renamed = _path_request(
            hub_api_endpoint=hub_api_endpoint,
            token=token,
            server=server,
            destination=created_path,
            user=user,
            method="patch",
            data={"path": new_path},
        )
        if renamed is None:  # pragma: no cover - PATCH returns decoded output
            raise JupyterHubResponseError(
                "Jupyter did not return the renamed path model"
            )
        return renamed

    return add_path_response


def delete_path(
    hub_api_endpoint: str,
    token: str,
    server: str,
    path: str,
    user: Optional[str] = None,
) -> None:
    """Delete a file or empty directory from a running Jupyter server.

    Args:
        hub_api_endpoint: Base JupyterHub REST API URL.
        token: JupyterHub API token used for authentication.
        server: Server hosting the path.
        path: File or empty-directory path to delete.
        user: Optional server owner. If omitted, the token owner is used.
    """
    values = {
        "hub_api_endpoint": hub_api_endpoint,
        "token": token,
        "server": server,
        "path": path,
    }
    _validate_server(values)
    _validate_required(values, "path")
    _path_request(
        hub_api_endpoint=hub_api_endpoint,
        token=token,
        server=server,
        path=path,
        user=user,
        method="delete",
    )


def upload_file(
    hub_api_endpoint: str,
    token: str,
    server: str,
    file: str,
    destination: str,
    user: Optional[str] = None,
) -> JsonObject:
    """Upload a local file to a running Jupyter server.

    Args:
        hub_api_endpoint: Base JupyterHub REST API URL.
        token: JupyterHub API token used for authentication.
        server: Destination server.
        file: Local filesystem path of the file to upload.
        destination: Existing destination file or directory on the server.
        user: Optional server owner. If omitted, the token owner is used.

    Returns:
        Jupyter Contents API model of the uploaded file.

    Raises:
        JupyterHubFileError: If the local file cannot be opened or read.
        JupyterHubResponseError: If the destination model is malformed.
    """
    values = {
        "hub_api_endpoint": hub_api_endpoint,
        "token": token,
        "server": server,
        "file": file,
        "destination": destination,
    }
    _validate_server(values)
    _validate_required(values, "file", "destination")
    _validate_non_empty(values, "file")

    server_destination = get_path(
        hub_api_endpoint=hub_api_endpoint,
        token=token,
        server=server,
        path=destination,
        user=user,
    )

    destination_type = server_destination.get("type")
    if destination_type == "file":
        jupyter_file_dest = destination
    elif destination_type == "directory":
        jupyter_file_dest = os.path.join(destination, os.path.basename(file))
    else:
        raise JupyterHubResponseError(
            "Jupyter destination response does not contain a valid 'type' field"
        )

    try:
        with open(file, "rb") as file_handle:
            content = base64.standard_b64encode(file_handle.read()).decode("utf-8")
    except OSError as exc:
        logger.info("Failed to read local upload source %s", file)
        raise JupyterHubFileError(f"Failed to read local file '{file}': {exc}") from exc

    data: JsonObject = {
        "content": content,
        "format": "base64",
        "name": os.path.basename(jupyter_file_dest),
        "type": "file",
        "path": jupyter_file_dest,
    }
    result = _path_request(
        hub_api_endpoint=hub_api_endpoint,
        token=token,
        server=server,
        destination=destination,
        user=user,
        method="put",
        data=data,
    )
    if result is None:  # pragma: no cover - PUT returns decoded output
        raise JupyterHubResponseError("Jupyter did not return the uploaded file model")
    return result


def exec_command(
    hub_api_endpoint: str,
    token: str,
    server: str,
    command: StringSequence,
    user: Optional[str] = None,
    output: str = "text",
) -> Union[str, JsonObject]:
    """Execute a shell command through the JupyterLab control endpoint.

    The target single-user server must have the ``jupyterlab_control_exec``
    Jupyter Server extension installed and enabled. The extension provides the
    ``jlab-control/exec`` endpoint used by this operation.

    Args:
        hub_api_endpoint: Base JupyterHub REST API URL.
        token: JupyterHub API token used for authentication.
        server: Server on which the command is executed.
        command: Shell command represented as a sequence of strings. The
            server-side extension joins the values before executing them through
            the shell, so shell operators can be included when required.
        user: Optional server owner. If omitted, the token owner is used.
        output: ``"text"`` returns only the command output string; ``"json"``
            returns the complete response object.

    Returns:
        Command output as text or the complete JSON response.
    """
    values = {
        "hub_api_endpoint": hub_api_endpoint,
        "token": token,
        "server": server,
        "command": command,
        "output": output,
    }
    _validate_server(values)
    _validate_required(values, "command")
    _validate_non_empty(values, "command")
    _validate_choice(values, "output", ("json", "text"))

    user_output = _get_full_user_output(hub_api_endpoint, token, user)
    server_url = _get_server_url(hub_api_endpoint, server, user_output)
    try:
        response = _make_request(
            hub_api_endpoint=server_url,
            token=token,
            method="post",
            api_request_endpoint="jlab-control/exec",
            data={"command": list(command)},
        )
    except JupyterHubNotFoundError as exc:
        raise JupyterHubNotFoundError(
            exc.status_code,
            "The jlab-control/exec endpoint is unavailable. Make sure the "
            "jupyterlab_control_exec Jupyter Server extension is installed "
            "and enabled on the target single-user server.",
            reason=exc.reason,
            url=exc.url,
        ) from exc
    decoded_response = _decode_response(response)

    if output == "text":
        command_output = decoded_response.get("output")
        if not isinstance(command_output, str):
            raise JupyterHubResponseError(
                "Command response does not contain a valid 'output' string"
            )
        return command_output
    return decoded_response


class JupyterHubClient:
    """Stateful client for the public JupyterHub adapter operations.

    The client stores connection-wide parameters once and exposes the adapter's
    operations as methods. This is the recommended public API when an
    application performs more than one operation against the same Hub because
    callers do not need to repeat ``hub_api_endpoint`` and ``token`` for every
    request.

    Args:
        hub_api_endpoint: Base URL of the JupyterHub REST API, normally ending
            in ``/hub/api/``.
        token: JupyterHub API token sent as the Bearer credential for requests.
        user: Optional default target user. Individual method calls may override
            this value when an operation must be performed for another user.

    Raises:
        JupyterHubValidationError: If the endpoint or token is missing or
            otherwise invalid.
    """

    def __init__(
        self,
        hub_api_endpoint: str,
        token: str,
        user: Optional[str] = None,
    ) -> None:
        values = {"hub_api_endpoint": hub_api_endpoint, "token": token}
        _validate_common(values)
        self.hub_api_endpoint = hub_api_endpoint
        self.token = token
        self.user = user

    def _user(self, user: Optional[str]) -> Optional[str]:
        """Resolve a per-call user override against the instance default."""
        return self.user if user is None else user

    def get_user(
        self,
        include_stopped_servers: bool = False,
        user: Optional[str] = None,
    ) -> JsonObject:
        """Return a JupyterHub user model.

        Args:
            include_stopped_servers: Include stopped named servers in the user
                model when the Hub supports that query option.
            user: Optional user overriding the default configured on the client.

        Returns:
            The user model returned by JupyterHub.
        """
        return get_user(
            self.hub_api_endpoint,
            self.token,
            user=self._user(user),
            include_stopped_servers=include_stopped_servers,
        )

    def get_servers(
        self,
        include_stopped_servers: bool = False,
        user: Optional[str] = None,
    ) -> JsonObject:
        """Return the server mapping for a JupyterHub user.

        Args:
            include_stopped_servers: Include stopped named servers when
                supported by the Hub.
            user: Optional user overriding the client default.

        Returns:
            The ``servers`` mapping from the selected JupyterHub user model.
        """
        return get_servers(
            self.hub_api_endpoint,
            self.token,
            user=self._user(user),
            include_stopped_servers=include_stopped_servers,
        )

    def start_server(
        self,
        server: str,
        options: ServerOptions = None,
        user: Optional[str] = None,
    ) -> None:
        """Start a named or default JupyterHub server.

        Args:
            server: Server name. Use an empty string for the default unnamed
                server.
            options: Optional spawner options as a mapping or JSON object string.
            user: Optional user overriding the client default.
        """
        start_server(
            self.hub_api_endpoint,
            self.token,
            server,
            user=self._user(user),
            options=options,
        )

    def stop_server(self, server: str, user: Optional[str] = None) -> None:
        """Stop a named or default JupyterHub server.

        Args:
            server: Server name. Use an empty string for the default server.
            user: Optional user overriding the client default.
        """
        stop_server(
            self.hub_api_endpoint,
            self.token,
            server,
            user=self._user(user),
        )

    def add_token(
        self,
        expiration: Optional[int] = None,
        note: Optional[str] = None,
        role: StringSequence = (),
        scope: StringSequence = (),
        user: Optional[str] = None,
    ) -> JsonObject:
        """Create a JupyterHub API token.

        Args:
            expiration: Requested token lifetime in seconds. Zero requests a
                non-expiring token when supported by the Hub.
            note: Optional human-readable description.
            role: Optional roles for the new token. Roles and scopes are
                mutually exclusive.
            scope: Optional scopes for the new token. Scopes and roles are
                mutually exclusive.
            user: Optional user overriding the client default.

        Returns:
            The API token model returned by JupyterHub.
        """
        return add_token(
            self.hub_api_endpoint,
            self.token,
            user=self._user(user),
            expiration=expiration,
            note=note,
            role=role,
            scope=scope,
        )

    def list_tokens(self, user: Optional[str] = None) -> JsonObject:
        """Return API-token information for a JupyterHub user."""
        return list_tokens(
            self.hub_api_endpoint,
            self.token,
            user=self._user(user),
        )

    def get_token(self, api_token_id: str, user: Optional[str] = None) -> JsonObject:
        """Return one JupyterHub API token model by token ID."""
        return get_token(
            self.hub_api_endpoint,
            self.token,
            api_token_id,
            user=self._user(user),
        )

    def delete_token(self, api_token_id: str, user: Optional[str] = None) -> None:
        """Delete one JupyterHub API token by token ID."""
        delete_token(
            self.hub_api_endpoint,
            self.token,
            api_token_id,
            user=self._user(user),
        )

    def add_shared_access(
        self,
        server: str,
        grant_to_user: Optional[str] = None,
        grant_to_group: Optional[str] = None,
        scope: StringSequence = (),
        user: Optional[str] = None,
    ) -> JsonObject:
        """Grant a user or group access to a server.

        Exactly one of ``grant_to_user`` and ``grant_to_group`` must be set.
        ``user`` identifies the owner of the server when it differs from the
        client default.
        """
        return add_shared_access(
            self.hub_api_endpoint,
            self.token,
            server,
            user=self._user(user),
            grant_to_user=grant_to_user,
            grant_to_group=grant_to_group,
            scope=scope,
        )

    def remove_shared_access(
        self,
        server: str,
        remove_from_user: Optional[str] = None,
        remove_from_group: Optional[str] = None,
        scope: StringSequence = (),
        remove_all: bool = False,
        user: Optional[str] = None,
    ) -> Optional[JsonObject]:
        """Remove selected or all shared access from a server."""
        return remove_shared_access(
            self.hub_api_endpoint,
            self.token,
            server,
            user=self._user(user),
            remove_from_user=remove_from_user,
            remove_from_group=remove_from_group,
            scope=scope,
            remove_all=remove_all,
        )

    def list_shared_access(
        self,
        server: str,
        user: Optional[str] = None,
    ) -> JsonObject:
        """Return sharing information for a server."""
        return list_shared_access(
            self.hub_api_endpoint,
            self.token,
            server,
            user=self._user(user),
        )

    def get_path(
        self,
        server: str,
        path: str,
        show_content: bool = False,
        user: Optional[str] = None,
    ) -> JsonObject:
        """Return a file or directory model from the Jupyter Contents API."""
        return get_path(
            self.hub_api_endpoint,
            self.token,
            server,
            path,
            user=self._user(user),
            show_content=show_content,
        )

    def add_path(
        self,
        server: str,
        destination: str,
        path_type: str,
        name: Optional[str] = None,
        copy_from: Optional[str] = None,
        user: Optional[str] = None,
    ) -> JsonObject:
        """Create a file or directory through the Jupyter Contents API."""
        return add_path(
            self.hub_api_endpoint,
            self.token,
            server,
            destination,
            path_type,
            user=self._user(user),
            name=name,
            copy_from=copy_from,
        )

    def delete_path(
        self,
        server: str,
        path: str,
        user: Optional[str] = None,
    ) -> None:
        """Delete a file or empty directory through the Contents API."""
        delete_path(
            self.hub_api_endpoint,
            self.token,
            server,
            path,
            user=self._user(user),
        )

    def upload_file(
        self,
        server: str,
        file: str,
        destination: str,
        user: Optional[str] = None,
    ) -> JsonObject:
        """Upload a local file to a running Jupyter server."""
        return upload_file(
            self.hub_api_endpoint,
            self.token,
            server,
            file,
            destination,
            user=self._user(user),
        )

    def exec_command(
        self,
        server: str,
        command: StringSequence,
        output: str = "text",
        user: Optional[str] = None,
    ) -> Union[str, JsonObject]:
        """Execute a shell command through the JupyterLab control endpoint.

        The target single-user server must have the ``jupyterlab_control_exec``
        Jupyter Server extension installed and enabled.

        Args:
            server: Target Jupyter server. Use an empty string for the default
                server.
            command: Shell command represented as a sequence of strings. The
                server-side extension joins the values before shell execution.
            output: ``"text"`` for only the command output string or ``"json"``
                for the complete response object.
            user: Optional user overriding the client default.
        """
        return exec_command(
            self.hub_api_endpoint,
            self.token,
            server,
            command,
            user=self._user(user),
            output=output,
        )
